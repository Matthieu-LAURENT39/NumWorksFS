from __future__ import annotations

import asyncio
import logging
import os
from errno import EIO, ENOENT
from functools import wraps
from io import BytesIO
from pathlib import Path
from stat import S_IFDIR, S_IFREG
from typing import Callable, NoReturn

import upsilon_py
from fuse import FuseOSError, LoggingMixIn, Operations, fuse_exit

from NumworksFS.storage_handler import NumworkFile, NumworksStorage

logger = logging.getLogger(__name__)


def needs_connection(func: Callable):
    @wraps(func)
    def wrapper(self: "NumworksFS", *args, **kwargs):
        # If we're not connected anymore
        if (
            self.loop.run_until_complete(self.numworks.status())["status"]
            != "connected"
        ):
            # We don't reconnect, the script exits
            self._exit()

        return func(self, *args, **kwargs)

    return wrapper


class NumworksFS(Operations, LoggingMixIn):
    """A read-write filesystem to access numworks files"""

    async def _setup_numworks(self):
        logger.info("Setting up numworks connection.")
        self.numworks = upsilon_py.NumWorks()
        await self.numworks.start()
        await self.numworks.connect()
        logger.info("Numworks connection ready!")

    def _exit(self) -> NoReturn:
        fuse_exit()
        self.loop.run_until_complete(self.numworks.stop())
        exit(0)

    def __init__(self) -> None:
        self.root = "/"
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self._setup_numworks())

    def _assert_file_path_valid(self, path: Path, /) -> None:
        # Can only create files at root
        if not path.parent == Path(self.root):
            raise FuseOSError(EIO)
        # Can only create .py files
        if not path.suffix == ".py":
            raise FuseOSError(EIO)

    @needs_connection
    def readdir(self, path, fh):
        logger.info(f"Reading dir {path}")
        p = Path(path)
        if p.absolute() != Path(self.root):
            raise FuseOSError(EIO)

        with NumworksStorage(self.numworks, self.loop) as s:
            file_names = [str(f.filename) for f in s.files]
        return [".", ".."] + file_names

    @needs_connection
    def read(self, path, size, offset, fh):
        logger.info(f"Reading file {path}. {size=}, {offset=}")
        with NumworksStorage(self.numworks, self.loop) as s:
            file = s.get_file(Path(path).name)
        f = BytesIO(file.content.encode("utf-8"))
        f.seek(offset)
        return f.read(size)

    @needs_connection
    def getattr(self, path, fh=None):
        logger.info(f"Getting attr for {path}")

        if path == self.root:
            size = 0
        else:
            with NumworksStorage(self.numworks, self.loop) as s:
                file = s.get_file(Path(path).name)
                if file is None:
                    raise FuseOSError(ENOENT)
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

    @needs_connection
    def create(self, path, mode=0o777):
        logger.info(f"Creating file {path}. {mode=}")
        p = Path(path)
        self._assert_file_path_valid(p)

        with NumworksStorage(self.numworks, self.loop) as s:
            s.files.append(NumworkFile(p.name.removesuffix(".py"), ""))
        return 0

    # def mkdir(self, path, mode):
    #     logger.info(f"Attempted mkdir with {path = }")
    #     raise FuseOSError(EIO)

    @needs_connection
    def write(self, path, data, offset, fh):
        logger.info(f"Writting to file {path}.")
        p = Path(path)
        self._assert_file_path_valid(p)

        with NumworksStorage(self.numworks, self.loop) as s:
            file = s.get_file(p.name)
            content = b"" if file is None else file.content.encode("utf-8")

            # Write in the BytesIO
            b = BytesIO(content)
            b.seek(offset, 0)
            b.write(data)
            b.seek(0)

            # Reflect changes on numworks
            file.content = b.getvalue().decode("utf-8")

        return len(data)

    @needs_connection
    def unlink(self, path):
        logger.info(f"Unlinking file {path}.")

        p = Path(path)
        with NumworksStorage(self.numworks, self.loop) as s:
            file = s.get_file(p.name)
            if file is None:
                raise FuseOSError(ENOENT)
            s.files.remove(file)

    @needs_connection
    def rename(self, old_path, new_path) -> None:
        logger.info(f"Renaming file: {old_path} -> {new_path}")
        old_p = Path(old_path)
        new_p = Path(new_path)
        self._assert_file_path_valid(new_p)

        with NumworksStorage(self.numworks, self.loop) as s:
            file = s.get_file(old_p.name)
            if file is None:
                raise FuseOSError(ENOENT)
            file.name = new_p.name.removesuffix(".py")

    @needs_connection
    def statfs(self, path):
        logger.info(f"Statfs for path {path}")

        if path != self.root:
            raise FuseOSError(EIO)

        info = self.loop.run_until_complete(self.numworks.get_platform_info())
        with NumworksStorage(self.numworks, self.loop) as s:
            used = sum(f.size for f in s.files)

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

    @needs_connection
    def ioctl(self, path, cmd, arg, fh, flags, data):
        logger.info(f"IOctl: {path=}, {cmd=}, {arg=}, {fh=}, {flags=}, {data=}")
        # * Required for nano and micro to work
        if cmd == 0x5401:
            return True

    @needs_connection
    def truncate(self, path, length, fh=None):
        logger.info(f"Truncating file {path}. {length=}")
        p = Path(path)
        self._assert_file_path_valid(p)

        with NumworksStorage(self.numworks, self.loop) as s:
            file = s.get_file(p.name)
            if file is None:
                file = NumworkFile(p.name.removesuffix(".py"), "")

            file.content = file.content[:length].ljust(length, "\0")
