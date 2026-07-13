"""CLI handler for ``sase memory review``."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

from sase.memory.proposals import (
    MemoryProposalError,
    MemoryProposalReviewError,
    MemoryProposalReviewResult,
    ProposalReviewer,
    approve_memory_proposal,
    memory_proposal_ledger_event_to_dict,
    memory_proposal_ledger_path,
    memory_proposal_state_to_dict,
    prepare_memory_proposal_edit,
    read_memory_proposal_events,
    read_memory_proposals,
    reject_memory_proposal,
    require_proposal_reviewer,
    resolve_memory_proposal_id,
)


def handle_memory_review_command(args: argparse.Namespace) -> None:
    """Review pending long-term memory proposals."""
    try:
        _validate_review_args(args)
        action = _selected_action(args)
        if action is None:
            _handle_interactive_or_static_list(args)
            return
        if action == "list":
            _handle_list(args)
            return
        if action == "show":
            _handle_show(args)
            return
        if action == "reject":
            _handle_reject(args)
            return
        if action == "approve":
            _handle_approve(args)
            return
        if action == "edit":
            _handle_edit(args)
            return
    except (MemoryProposalError, OSError, UnicodeError) as exc:
        print(f"sase memory review: {exc}", file=sys.stderr)
        sys.exit(1)


def _selected_action(args: argparse.Namespace) -> str | None:
    if args.list:
        return "list"
    if args.show:
        return "show"
    if args.reject:
        return "reject"
    if args.approve:
        return "approve"
    if args.edit:
        return "edit"
    return None


def _validate_review_args(args: argparse.Namespace) -> None:
    action = _selected_action(args)
    if action is None:
        if args.proposal_id:
            raise MemoryProposalReviewError(
                "pass --show, --approve, --edit, or --reject with a proposal id"
            )
        if args.reason:
            raise MemoryProposalReviewError("--reason is only valid with --reject")
        if args.target:
            raise MemoryProposalReviewError("--target is only valid with approval")
        if args.edited_file:
            raise MemoryProposalReviewError("--edited-file is only valid with approval")
        return
    if action == "list":
        if args.proposal_id:
            raise MemoryProposalReviewError("--list does not accept a proposal id")
        if args.reason:
            raise MemoryProposalReviewError("--reason is only valid with --reject")
        if args.target:
            raise MemoryProposalReviewError("--target is only valid with approval")
        if args.edited_file:
            raise MemoryProposalReviewError(
                "--edited-file is only valid with --approve"
            )
        return

    if not args.proposal_id:
        raise MemoryProposalReviewError(f"--{action} requires a proposal id")
    if args.all:
        raise MemoryProposalReviewError("--all is only valid with --list")
    if args.reason and action != "reject":
        raise MemoryProposalReviewError("--reason is only valid with --reject")
    if action == "reject":
        if args.target:
            raise MemoryProposalReviewError("--target is only valid with approval")
        if args.edited_file:
            raise MemoryProposalReviewError(
                "--edited-file is only valid with --approve"
            )
        if not (args.reason or "").strip():
            raise MemoryProposalReviewError(
                "memory proposal rejection reason is required"
            )
    if action == "show":
        if args.target:
            raise MemoryProposalReviewError("--target is only valid with approval")
        if args.edited_file:
            raise MemoryProposalReviewError(
                "--edited-file is only valid with --approve"
            )
    if action == "edit" and args.edited_file:
        raise MemoryProposalReviewError("--edited-file is only valid with --approve")


def _handle_list(args: argparse.Namespace) -> None:
    states = read_memory_proposals()
    if not args.all:
        states = tuple(state for state in states if state.status == "pending")
    payload = {
        "count": len(states),
        "ledger_path": str(memory_proposal_ledger_path(cwd=Path.cwd())),
        "proposals": [memory_proposal_state_to_dict(state) for state in states],
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return

    if not states:
        print("No memory proposals match the current filters.")
        return
    print(f"Memory Proposals ({len(states)})")
    for state in states:
        print(
            f"{state.status:<19} {state.proposal_id}  "
            f"{state.target_path}  {state.title}"
        )


def _handle_show(args: argparse.Namespace) -> None:
    state = resolve_memory_proposal_id(args.proposal_id, read_memory_proposals())
    events = tuple(
        event
        for event in read_memory_proposal_events()
        if event.proposal_id == state.proposal_id
    )
    payload = {
        "body": _read_optional_text(Path(state.body_path)),
        "events": [memory_proposal_ledger_event_to_dict(event) for event in events],
        "ledger_path": str(memory_proposal_ledger_path(cwd=Path.cwd())),
        "proposal": memory_proposal_state_to_dict(state),
        "reviewed_body": (
            _read_optional_text(Path(state.reviewed_body_path))
            if state.reviewed_body_path
            else None
        ),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return

    _print_show(payload)


def _handle_reject(args: argparse.Namespace) -> None:
    result = reject_memory_proposal(args.proposal_id, reason=args.reason)
    payload = _review_result_payload(result)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return
    print(f"Rejected memory proposal: {result.state.proposal_id}")
    print(f"reason: {result.state.review_reason}")


def _handle_approve(args: argparse.Namespace) -> None:
    result = approve_memory_proposal(
        args.proposal_id,
        target=args.target,
        edited_file=args.edited_file,
    )
    _print_or_emit_approval(result, json_output=args.json)


def _handle_edit(args: argparse.Namespace) -> None:
    result = edit_memory_proposal_via_editor(args.proposal_id, target=args.target)
    _print_or_emit_approval(result, json_output=args.json)


def edit_memory_proposal_via_editor(
    proposal_id: str,
    *,
    target: str | None = None,
) -> MemoryProposalReviewResult:
    """Open the proposal in ``$VISUAL``/``$EDITOR`` and approve edited content."""
    editor = _editor_command()
    if editor is None:
        raise MemoryProposalReviewError("$VISUAL or $EDITOR must be set for --edit")
    reviewer = require_proposal_reviewer()
    reviewed_path = prepare_memory_proposal_edit(
        proposal_id,
        reviewer=reviewer,
    )
    _run_editor(editor, reviewed_path)
    return approve_memory_proposal(
        proposal_id,
        target=target,
        edited_file=reviewed_path,
        reviewer=reviewer,
    )


def _print_or_emit_approval(
    result: MemoryProposalReviewResult, *, json_output: bool
) -> None:
    payload = _review_result_payload(result)
    if json_output:
        print(json.dumps(payload, sort_keys=True))
        return
    print(f"Approved memory proposal: {result.state.proposal_id}")
    print(f"status: {result.state.status}")
    print(f"target: {result.state.target_path}")
    if result.canonical_path is not None:
        print(f"canonical: {result.canonical_path}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"- {warning.code}: {warning.message}")


def _review_result_payload(result: MemoryProposalReviewResult) -> dict[str, Any]:
    return {
        "canonical_path": str(result.canonical_path)
        if result.canonical_path is not None
        else None,
        "event": memory_proposal_ledger_event_to_dict(result.event),
        "ledger_path": str(result.ledger_path),
        "proposal": memory_proposal_state_to_dict(result.state),
        "reviewed_path": str(result.reviewed_path)
        if result.reviewed_path is not None
        else None,
        "warnings": [asdict(warning) for warning in result.warnings],
    }


def _editor_command() -> tuple[str, ...] | None:
    raw_editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if raw_editor is None or not raw_editor.strip():
        return None
    command = tuple(shlex.split(raw_editor))
    return command or None


def _run_editor(command: tuple[str, ...], path: Path) -> None:
    try:
        result = subprocess.run(
            [*command, str(path)],
            check=False,
        )
    except OSError as exc:
        raise MemoryProposalReviewError(f"failed to run editor: {command[0]}") from exc
    if result.returncode != 0:
        raise MemoryProposalReviewError(
            f"editor exited with status {result.returncode}"
        )


def _print_show(payload: dict[str, Any]) -> None:
    proposal = payload["proposal"]
    print(f"Memory Proposal {proposal['proposal_id']}")
    print(f"status: {proposal['status']}")
    print(f"title: {proposal['title']}")
    print(f"target: {proposal['target_path']}")
    print(f"author: {proposal['author_name']} ({proposal['author_source']})")
    print("")
    print("Evidence:")
    for evidence in proposal["evidence"]:
        detail = (
            evidence.get("resolved_path")
            or evidence.get("chat_id")
            or evidence.get("url")
            or evidence.get("note")
            or evidence["raw"]
        )
        print(f"- {evidence['kind']}: {detail}")
    if proposal["warnings"]:
        print("")
        print("Warnings:")
        for warning in proposal["warnings"]:
            print(f"- {warning['code']}: {warning['message']}")
    print("")
    print("Body:")
    print(payload["body"] or "")


def _read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _handle_interactive_or_static_list(args: argparse.Namespace) -> None:
    if _should_launch_interactive_review(args):
        _launch_interactive_review()
        return

    if not args.json:
        print(
            "Non-interactive terminal detected; showing pending proposals. "
            "Use `sase memory review --list` for explicit list mode."
        )
    _handle_list(args)


def _should_launch_interactive_review(args: argparse.Namespace) -> bool:
    if args.json or args.all:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _launch_interactive_review() -> None:
    from sase.memory.review_tui import MemoryReviewTuiApp

    MemoryReviewTuiApp().run()
