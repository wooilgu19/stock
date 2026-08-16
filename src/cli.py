"""Small deployment-time command line utilities."""

import argparse
import sys

from src.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock trading service utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-config", help="validate configuration without starting workers"
    )
    validate.add_argument(
        "--live", action="store_true",
        help="also require credentials for live broker access",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-config":
        settings = Settings()
        if args.live:
            settings.validate_for_live()
        mode = "live" if args.live else "paper"
        print(f"configuration valid ({mode})")
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"configuration invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
