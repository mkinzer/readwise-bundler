"""Command line.

    python -m readwise_bundler run [--dry-run] [--thumbnails alternate|collage|list|none]
    python -m readwise_bundler refresh [--dry-run] [--thumbnails ...]
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

from .api import ReaderClient
from .run import TARGET_OPEN, Run

THUMBNAIL_CHOICES = ("alternate", "collage", "list", "none")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="readwise_bundler", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--dry-run", action="store_true",
                       help="show what would happen without changing anything in Reader")
        p.add_argument("--thumbnails", choices=THUMBNAIL_CHOICES,
                       default=os.environ.get("BUNDLER_THUMBNAILS") or "list",
                       help="thumbnail style; 'alternate' gives odd bundles a collage, even ones a list "
                            "(default: $BUNDLER_THUMBNAILS or list)")
        p.add_argument("--preview", type=Path, metavar="DIR",
                       help="also write each bundle (and its thumbnail) to files in DIR")

    run = sub.add_parser("run", help="settle finished bundles and top the shelf up")
    common(run)
    run.add_argument("--target", type=int, default=TARGET_OPEN,
                     help=f"how many unfinished bundles to keep waiting (default {TARGET_OPEN})")
    run.add_argument("--seed", type=int, help="make the random choices repeatable")

    refresh = sub.add_parser("refresh", help="give waiting bundles the current title format and a thumbnail")
    common(refresh)

    args = parser.parse_args(argv)
    token = os.environ.get("READWISE_TOKEN", "").strip()
    if not token:
        print("READWISE_TOKEN is not set. Get yours at https://readwise.io/access_token", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set: labels will be taken from the titles.", file=sys.stderr)

    client = ReaderClient(token)
    if args.command == "refresh":
        Run(client, dry_run=args.dry_run, thumbnails=args.thumbnails, preview_dir=args.preview).refresh()
        return 0
    rng = random.Random(args.seed) if args.seed is not None else None
    Run(client, target=args.target, dry_run=args.dry_run, rng=rng, preview_dir=args.preview,
        thumbnails=args.thumbnails).go()
    return 0


if __name__ == "__main__":
    sys.exit(main())
