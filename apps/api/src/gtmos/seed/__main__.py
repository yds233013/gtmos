"""python -m gtmos.seed [--reset] [--if-empty] [--accounts N]"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from sqlalchemy import select, text

from gtmos.config import get_settings
from gtmos.db import get_engine, session_scope
from gtmos.models import Base, Workspace


def reset_data() -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the deterministic GTMOS DEMO dataset.")
    parser.add_argument("--reset", action="store_true", help="truncate all GTMOS tables first")
    parser.add_argument("--if-empty", action="store_true", help="do nothing if a workspace already exists")
    parser.add_argument("--accounts", type=int, default=get_settings().seed_accounts)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with session_scope() as db:
        exists = db.scalars(select(Workspace.id)).first() is not None
    if exists and args.if_empty:
        print("Workspace already exists; skipping seed (--if-empty).")
        return 0
    if exists and not args.reset:
        print("Data already present. Re-run with --reset to reload the demo dataset.", file=sys.stderr)
        return 1
    if args.reset:
        reset_data()
    from gtmos.seed.generator import seed

    t0 = time.perf_counter()
    with session_scope() as db:
        summary = seed(db, size=args.accounts)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
