"""Command-line entry point: `uv run airport-agent <command>`."""

from __future__ import annotations

import argparse

from airport_agent.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="airport-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="Show active settings")
    args = parser.parse_args()

    if args.command == "info":
        for key, value in vars(settings).items():
            print(f"{key:15} {value}")


if __name__ == "__main__":
    main()
