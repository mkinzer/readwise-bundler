"""Command line: ``python -m readwise_bundler run [--dry-run]``."""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

from .api import ReaderClient
from .run import TARGET_OPEN, Run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="readwise_bundler", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="settle finished bundles and top the shelf up")
    run.add_argument("--dry-run", action="store_true",
                     help="show what would happen without changing anything in Reader")
    run.add_argument("--target", type=int, default=TARGET_OPEN,
                     help=f"how many unfinished bundles to keep waiting (default {TARGET_OPEN})")
    run.add_argument("--seed", type=int, help="make the random choices repeatable")
    run.add_argument("--preview", type=Path, metavar="DIR",
                     help="also write each bundle as an HTML file in DIR")
    args = parser.parse_args(argv)

    token = os.environ.get("READWISE_TOKEN", "").strip()
    if not token:
        print("READWISE_TOKEN is not set. Get yours at https://readwise.io/access_token", file=sys.stderr)
        return 2

    client = ReaderClient(token)
    rng = random.Random(args.seed) if args.seed is not None else None
    Run(client, target=args.target, dry_run=args.dry_run, rng=rng, preview_dir=args.preview).go()
    return 0


if __name__ == "__main__":
    sys.exit(main())
