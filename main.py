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
from io import BytesIO

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


@dataclass
class NumworkFile:
    filename: str
    content: str

    @property
    def name(self) -> str:
        return self.filename.removesuffix(".py")

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
            raise FuseOSError(ENOENT) from None

    def __init__(self):
        self.root = "/"
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self._setup_numworks())

    def readdir(self, path, fh):
        logger.info(f"Reading dir {path}")
        p = Path(path)
        if p.absolute() != Path(self.root):
            raise FuseOSError(EIO)

        files = self._get_files()
        file_paths = [str(f.filename) for f in files]
        return [".", ".."] + file_paths

    def read(self, path, size, offset, fh):
        logger.info(f"Reading file {path}. {size=}, {offset=}")
        file = self._get_file(Path(path).name)
        f = BytesIO(file.content.encode("utf-8"))
        f.seek(offset)
        return f.read(size)

    def getattr(self, path, fh=None):
        logger.info(f"Getting attr for {path}")

        if path == self.root:
            size = 0
        else:
            file = self._get_file(Path(path).name)
            size = file.size

        mode_base = S_IFDIR if path == self.root else S_IFREG

        return dict(
            st_mode=(mode_base | 0o777),
            st_nlink=1,
            st_size=size,
            # st_ctime=0,
            # st_mtime=0,
            # st_atime=0,
            st_uid=os.getuid(),
            st_gid=os.getgid(),
        )

    # It's needed for some reason
    getxattr = None

    def _create_storage_file(self, storage: dict, name: str) -> dict:
        storage["records"].append(
            {
                "name": name,
                "type": "py",
                "autoImport": False,
                "code": "",
            }
        )
        return storage

    def create(self, path, mode=0o777):
        logger.info(f"Creating file {path}. {mode=}")
        p = Path(path)

        # Can only create files at root
        if not p.parent == Path(self.root):
            raise FuseOSError(EIO)

        storage = self.loop.run_until_complete(self.numworks.backup_storage())
        storage = self._create_storage_file(storage, p.name.removesuffix(".py"))
        self.loop.run_until_complete(self.numworks.install_storage(storage))
        return 0

    # def mkdir(self, path, mode):
    #     logger.info(f"Attempted mkdir with {path = }")
    #     raise FuseOSError(EIO)

    def write(self, path, data, offset, fh):
        logger.info(f"Writting to file {path}.")
        p = Path(path)

        if not p.suffix == ".py":
            raise FuseOSError(EIO)

        try:
            f = self._get_file(p.name)
            content = f.content.encode("utf-8")
        except FuseOSError:
            f = None
            content = b""

        # Write in the BytesIO
        b = BytesIO(content)
        b.seek(offset, 0)
        b.write(data)
        b.seek(0)

        # Reflect the write on numworks
        storage = self.loop.run_until_complete(self.numworks.backup_storage())
        try:
            file = next(f for f in storage["records"] if f'{f["name"]}.py' == p.name)
        except StopIteration:
            storage = self._create_storage_file(storage, p.name.removesuffix(".py"))
            file = next(f for f in storage["records"] if f'{f["name"]}.py' == p.name)

        # * upsilon_py uses the wrong encoding, it
        # * uses iso-8859-1 while numworks uses utf-8,
        # * so we have to work around that.
        file["code"] = b.getvalue().decode("utf-8")
        self.loop.run_until_complete(self.numworks.install_storage(storage))

        return len(data)

    def unlink(self, path):
        logger.info(f"Unlinking file {path}.")

        p = Path(path)
        storage = self.loop.run_until_complete(self.numworks.backup_storage())
        try:
            file = next(f for f in storage["records"] if f'{f["name"]}.py' == p.name)
            storage["records"].remove(file)
        except StopIteration:
            raise FuseOSError(EIO) from None
        self.loop.run_until_complete(self.numworks.install_storage(storage))

    def rename(self, old_path, new_path) -> None:
        logger.info(f"Renaming file: {old_path} -> {new_path}")
        old_p = Path(old_path)
        new_p = Path(new_path)

        if not new_p.suffix == ".py":
            raise FuseOSError(EIO)
        if not new_p.parent == Path(self.root):
            raise FuseOSError(EIO)

        storage = self.loop.run_until_complete(self.numworks.backup_storage())
        try:
            file = next(
                f for f in storage["records"] if f'{f["name"]}.py' == old_p.name
            )
            file["name"] = new_p.name.removesuffix(".py")
        except StopIteration:
            raise FuseOSError(ENOENT) from None
        self.loop.run_until_complete(self.numworks.install_storage(storage))

    def statfs(self, path):
        logger.info(f"Statfs for path {path}")

        info = self.loop.run_until_complete(self.numworks.get_platform_info())
        used = sum(f.size for f in self._get_files())

        return {
            # No idea what the block size is and couldn't find any info
            "f_frsize": 1,
            # Space info
            "f_bavail": info["storage"]["size"] - used,
            "f_bfree": info["storage"]["size"] - used,
            "f_blocks": info["storage"]["size"],
            # Source: numworks website
            "f_namemax": 219,
        }


def main(
    mountpoint,
):
    FUSE(
        operations=NumworksFS(),
        mountpoint=mountpoint,
        encoding="utf-8",
        nothreads=True,
        foreground=True,
        allow_other=True,
    )


if __name__ == "__main__":
    main(sys.argv[1])
