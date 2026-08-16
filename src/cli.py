"""Small deployment-time command line utilities."""

import argparse
import sys

from src.config import Settings
from src.api.kis_rest import KISRestClient


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
    subparsers.add_parser(
        "check-kis-auth", help="perform an explicit KIS authentication smoke check"
    )
    price = subparsers.add_parser(
        "check-kis-price", help="perform a read-only KIS price smoke check"
    )
    price.add_argument("symbol", help="six-digit domestic stock symbol")
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
    if args.command == "check-kis-auth":
        settings = Settings()
        settings.validate_for_live()
        KISRestClient(
            settings.kis_base_url,
            settings.kis_appkey,
            settings.kis_appsecret,
        ).access_token()
        print("KIS authentication succeeded")
        return 0
    if args.command == "check-kis-price":
        if not args.symbol.isdigit() or len(args.symbol) != 6:
            raise ValueError("symbol must be a 6-digit code")
        settings = Settings()
        settings.validate_for_live()
        price = KISRestClient(
            settings.kis_base_url,
            settings.kis_appkey,
            settings.kis_appsecret,
        ).current_price(args.symbol)
        print(f"KIS price succeeded: {args.symbol}={price:g}")
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"configuration invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
