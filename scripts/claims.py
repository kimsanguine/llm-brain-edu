#!/usr/bin/env python3
"""Explicit claim-ledger build and read-only context commands."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from lib import claim_ledger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or read the persisted claims.jsonl ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="explicitly rebuild claims.jsonl from wiki + raw")
    build.add_argument("--wiki-root", type=Path, default=Path("wiki"))
    build.add_argument("--ledger", type=Path, default=Path("claims.jsonl"))
    build.add_argument("--slug", action="append", required=True)

    context = subparsers.add_parser("context", help="read and render query context without writes")
    context.add_argument("--wiki-root", type=Path, default=Path("wiki"))
    context.add_argument("--ledger", type=Path, default=Path("claims.jsonl"))
    context.add_argument("--slug", action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.wiki_root.resolve().parent
    try:
        if args.command == "build":
            records = claim_ledger.build_claim_ledger(
                args.slug, wiki_root=args.wiki_root, now=date.today()
            )
            claim_ledger.write_claims_jsonl(
                args.ledger, records, project_root=project_root
            )
            print(f"claim ledger written: {args.ledger} ({len(records)} records)")
            return 0

        records = claim_ledger.read_claims_jsonl(args.ledger)
        claim_ledger.validate_claim_source_inventory(records, wiki_root=args.wiki_root)
        selected = claim_ledger.claims_for_slugs(records, args.slug)
        print(
            claim_ledger.render_llm_context(
                selected, project_root=project_root, now=date.today()
            )
        )
        return 0
    except claim_ledger.ClaimSourceInventoryError as exc:
        print(
            f"claim ledger invalid: {exc}. Rebuild with: "
            f"{claim_ledger.CLAIM_REBUILD_COMMAND}",
            file=sys.stderr,
        )
        return 2
    except claim_ledger.ClaimLedgerError as exc:
        print(f"claim ledger invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
