from __future__ import annotations

from dataclasses import dataclass
import upsilon_py
import logging
from types import TracebackType
from asyncio import AbstractEventLoop
from copy import deepcopy

logger = logging.getLogger(__name__)


@dataclass
class NumworkFile:
    name: str
    content: str

    @property
    def filename(self) -> str:
        return f"{self.name}.py"

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))


def records_to_files(records: list[dict]) -> list[NumworkFile]:
    files = []
    for r in records:
        # TODO: Support other types of files
        if r["type"] != "py":
            continue
        # * upsilon_py uses the wrong encoding when decoding, it
        # * uses iso-8859-1 while numworks uses utf-8, so we
        # * have to work around that.
        content = r["code"].encode("iso-8859-1").decode("utf-8")
        files.append(
            NumworkFile(
                name=r["name"],
                content=content,
            )
        )
    return files


class NumworksStorage:
    def __init__(self, numworks: upsilon_py.NumWorks, loop: AbstractEventLoop) -> None:
        self._numworks = numworks
        self._loop = loop
        self.load()

    def __enter__(self) -> "NumworksStorage":
        logger.debug("Entering NumworksStorage context")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            logger.info("NumworksStorage context left due to exception, not saving")
            return
        # Saving is slow, so we avoid it if possible
        if not self.dirty:
            logger.info(
                "NumworksStorage context left normally but no file changed, not saving"
            )
            return

        logger.info("NumworksStorage context left normally + files changed, saving")
        self.save()

    @property
    def dirty(self) -> bool:
        """Whether the storage has been changed locally since the last load"""
        return self._old_files != self.files

    def load(self) -> None:
        """
        Gets the current state of the storage from the calculator
        This will cause unsaved modifications to be discarded
        """
        self.files = records_to_files(
            self._loop.run_until_complete(self._numworks.backup_storage())["records"]
        )
        self._old_files = deepcopy(self.files)

    def save(self) -> None:
        """Writes the current state of the storage to the calculator"""
        storage: list[dict] = self._loop.run_until_complete(
            self._numworks.backup_storage()
        )
        records = storage["records"]

        old_names = {r["name"] for r in records if r["type"] == "py"}
        new_names = {f.name for f in self.files}

        # Deleted files
        for name in old_names - new_names:
            logger.debug(f"Deleted file: {name}")
            file = next(f for f in records if f.get("name") == name)
            records.remove(file)
        # Modified files
        for name in old_names & new_names:
            logger.debug(f"Changed file: {name}")
            file = next(f for f in records if f.get("name") == name)
            file["code"] = self.get_file(f"{name}.py").content
        # New files
        for name in new_names - old_names:
            logger.debug(f"New file: {name}")
            records.append(
                {
                    "name": name,
                    "type": "py",
                    "autoImport": False,
                    "code": self.get_file(f"{name}.py").content,
                }
            )

        # Save the modified storage to the calculator
        self._loop.run_until_complete(self._numworks.install_storage(storage))

    def get_file(self, filename: str) -> NumworkFile | None:
        return next((f for f in self.files if f.filename == filename), None)
