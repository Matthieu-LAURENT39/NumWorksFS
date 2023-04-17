from fuse import FUSE

import logging
import argparse
import sys

from NumworksFS import NumworksFS


def main(mountpoint: str, *, foreground: bool):
    FUSE(
        operations=NumworksFS(),
        mountpoint=mountpoint,
        encoding="utf-8",
        nothreads=True,
        foreground=foreground,
        allow_other=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A FUSE to access your NumWorks calculator's files"
    )
    parser.add_argument("mount", help="directory to mount to", type=str)
    parser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true"
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-f",
        "--foreground",
        action="store_true",
        help="run in foreground mode",
    )
    mode.add_argument(
        "-b",
        "--background",
        action="store_true",
        help="run in background mode",
        default=True,
    )

    # reconnect_group = parser.add_mutually_exclusive_group(required=False)
    # reconnect_group.add_argument(
    #     "-r",
    #     "--reconnect",
    #     dest="reconnect",
    #     action="store_true",
    #     help="waits for the calculator to be plugged back in when connection is lost",
    # )
    # reconnect_group.add_argument(
    #     "--no-reconnect",
    #     dest="reconnect",
    #     action="store_false",
    #     help="exits as soon as the connection to the calculator is lost",
    # )
    # parser.set_defaults(reconnect=True)
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level)

    main(args.mount, foreground=args.foreground)
