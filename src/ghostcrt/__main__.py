from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ghostcrt import __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ghostcrt", description="SSH session manager TUI")
    parser.add_argument("--config", type=Path, default=None, help="Path to SSH config file")
    parser.add_argument("--vault", type=Path, default=None, help="Path to vault.enc")
    parser.add_argument("--theme", type=str, default=None, help="Textual theme name")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    from ghostcrt.app import GhostCRTApp

    app = GhostCRTApp(
        ssh_config=args.config,
        vault=args.vault,
        theme=args.theme,
    )
    app.run()


if __name__ == "__main__":
    main()
