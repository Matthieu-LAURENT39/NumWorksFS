from fuse import FUSE

import logging
import sys

from NumworksFS import NumworksFS


def main(mountpoint: str):
    FUSE(
        operations=NumworksFS(),
        mountpoint=mountpoint,
        encoding="utf-8",
        nothreads=True,
        foreground=True,
        allow_other=True,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    main(sys.argv[1])
