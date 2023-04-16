import os
import sys
import asyncio

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
from errno import EIO, ENOENT
from pathlib import Path
import upsilon_py
from dataclasses import dataclass
from stat import S_IFDIR, S_IFREG
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@dataclass
class NumworkFile:
    filename: str
    content: str


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
                filename=f"{r['name']}.py",
                content=content,
            )
        )
    return files


class NumworksFS(Operations, LoggingMixIn):
    """A read-only filesystem to access numworks files"""

    async def _setup_numworks(self):
        logger.info("Setting up numworks connection.")
        self.numworks = upsilon_py.NumWorks()
        await self.numworks.start()
        await self.numworks.connect()
        logger.info("Numworks connection ready!")

    def _get_files(self) -> list[NumworkFile]:
        files = records_to_files(
            self.loop.run_until_complete(self.numworks.backup_storage())["records"]
        )
        return files

    def _get_file(self, filename: str) -> NumworkFile:
        files = self._get_files()
        try:
            return next(f for f in files if f.filename == filename)
        except StopIteration:
            raise FuseOSError(ENOENT)

    def __init__(self):
        self.root = "/"
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self._setup_numworks())

    def readdir(self, path, fh):
        logger.debug(f"Reading dir {path}")
        p = Path(path)
        if p.absolute() != Path("/"):
            raise FuseOSError(EIO)

        files = self._get_files()
        file_paths = [str(f.filename) for f in files]
        return [".", ".."] + file_paths

    # TODO: take offset and size into account
    # Should probably use BytesIO for that
    def read(self, path, size, offset, fh):
        logger.debug(f"Reading file {path}. {size=}, {offset=}")
        file = self._get_file(Path(path).name)
        return file.content.encode()

    def getattr(self, path, fh=None):
        logger.debug(f"Getting attr for {path}")

        if path == "/":
            size = 0
        else:
            file = self._get_file(Path(path).name)
            size = len(file.content.encode("utf-8"))

        mode_base = S_IFDIR if path == "/" else S_IFREG

        return dict(
            st_mode=(mode_base | 0o555),
            st_nlink=1,
            st_size=size,
            st_ctime=0,
            st_mtime=0,
            st_atime=0,
            st_uid=os.getuid(),
            st_gid=os.getgid(),
        )

    # It's needed for some reason
    getxattr = None


def main(
    mountpoint,
):
    FUSE(
        operations=NumworksFS(),
        mountpoint=mountpoint,
        nothreads=True,
        foreground=True,
        allow_other=True,
    )


if __name__ == "__main__":
    main(sys.argv[1])
