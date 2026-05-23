"""CLI handler for ``sase memory write``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sase.memory.proposals import (
    MemoryProposalError,
    create_memory_proposal,
    memory_proposal_state_to_dict,
)


def handle_memory_write_command(args: argparse.Namespace) -> None:
    """Create a pending long-term memory proposal."""
    try:
        body = _read_body(args)
        evidence_values = _evidence_values(args)
        result = create_memory_proposal(
            title=args.title,
            body=body,
            evidence_values=evidence_values,
            target=args.target,
            slug=args.slug,
            keywords=args.keyword or (),
            manual_author=args.manual_author,
            allow_large=args.allow_large,
            cwd=Path.cwd(),
        )
    except (MemoryProposalError, OSError, UnicodeError) as exc:
        print(f"sase memory write: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "draft_path": str(result.draft_path),
        "ledger_path": str(result.ledger_path),
        "proposal": memory_proposal_state_to_dict(result.state),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return

    _print_human_result(payload)


def _read_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    if args.file is not None:
        return Path(args.file).read_text(encoding="utf-8")

    stdin = sys.stdin
    is_tty = getattr(stdin, "isatty", lambda: True)
    if is_tty():
        raise MemoryProposalError(
            "memory proposal body is required; pass --body, --file, or pipe stdin"
        )
    try:
        return stdin.read()
    except OSError as exc:
        raise MemoryProposalError(
            "memory proposal body is required; pass --body, --file, or pipe stdin"
        ) from exc


def _evidence_values(args: argparse.Namespace) -> tuple[str, ...]:
    values: list[str] = list(args.evidence or ())
    for chat_id in args.from_chat or ():
        values.append(f"chat:{chat_id}")
    return tuple(values)


def _print_human_result(payload: dict[str, Any]) -> None:
    proposal = payload["proposal"]
    print(f"Created memory proposal: {proposal['proposal_id']}")
    print(f"status: {proposal['status']}")
    print(f"target: {proposal['target_path']}")
    print(f"body: {payload['draft_path']}")
    print(f"ledger: {payload['ledger_path']}")
    warning_count = len(proposal["warnings"])
    if warning_count:
        print(f"warnings: {warning_count}")
