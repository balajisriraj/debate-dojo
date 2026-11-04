"""Command line: ``debatedojo serve | eval | formats``."""

from __future__ import annotations

import argparse
import asyncio
import sys


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("debatedojo.api:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


def _eval(args: argparse.Namespace) -> None:
    from .evals import run

    sys.exit(0 if asyncio.run(run(args.cases, verbose=args.verbose)) else 1)


def _formats(args: argparse.Namespace) -> None:
    from .config import get_settings
    from .formats import load_catalog

    settings = get_settings()
    catalog = load_catalog(settings.formats_dir, settings.personas_path)
    for fmt in catalog.formats.values():
        phases = ", ".join(f"{p.name} {p.exchanges}x{p.seconds}s" for p in fmt.phases)
        print(f"{fmt.mode:<8} {fmt.id:<16} {phases}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="debatedojo", description="Practise arguing with an AI that argues back.")
    commands = parser.add_subparsers(required=True)

    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8060)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(run=_serve)

    evals = commands.add_parser("eval", help="run the judge-calibration evals")
    evals.add_argument("--cases", default=None, help="path to a cases YAML file")
    evals.add_argument("--verbose", action="store_true")
    evals.set_defaults(run=_eval)

    commands.add_parser("formats", help="list the formats and their phases").set_defaults(run=_formats)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
