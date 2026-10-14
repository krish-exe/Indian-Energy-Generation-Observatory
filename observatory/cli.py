"""observatory CLI.

    python -m observatory refresh            # collect + build + export (the whole pipeline)
    python -m observatory refresh --fresh    # same, re-downloading every file from the sources
    python -m observatory collect | build | export
"""
from __future__ import annotations

import argparse
import sys
import time

from . import config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="observatory")
    ap.add_argument("command", choices=["collect", "build", "export", "refresh"])
    ap.add_argument("--fresh", action="store_true", help="ignore files already downloaded")
    ap.add_argument("--start", help="override window start (YYYY-MM-DD)")
    ap.add_argument("--end", help="override window end (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    cfg = config.load(start=args.start, end=args.end)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    t0 = time.time()
    print(f"window {cfg.start} .. {cfg.end} ({len(cfg.dates())} days)")

    if args.command in ("collect", "refresh"):
        from .collect import collect
        collect(cfg, fresh=args.fresh)
    if args.command in ("build", "refresh"):
        from .build import build
        build(cfg)
    if args.command in ("export", "refresh"):
        from .export import export
        export(cfg)
    print(f"done in {time.time() - t0:.0f}s")
