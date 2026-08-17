"""Attributed-evidence bead CLI command handlers: ``+1`` and ``note``."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.markup import escape

from sase.agent.identity import current_instant, resolve_observation_window_start
from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
from sase.bead.cli_crud_common import resolve_mutation_author
from sase.bead.model import Status
from sase.bead.mutation_commit import require_mutation_commit_message


def _withheld_reopen_note(reporter: str, closed_at: str) -> str:
    return (
        f"{reporter}'s +1 postdates the {closed_at} close, but its "
        "observation window does not, so the reopen was withheld and the "
        "bead was left closed. Re-file with --verified-after-close if this "
        "reproduces on a tree that already contains the close."
    )


def handle_bead_plus_one(args: argparse.Namespace) -> None:
    """Record independently attributed evidence on an existing task bead."""
    verified_after_close = bool(getattr(args, "verified_after_close", False))
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            reporter = getattr(args, "author", None)
            if reporter is None:
                reporter = resolve_mutation_author(mutation.project)
            if verified_after_close:
                target = mutation.project.show(args.id)
                if target.status is not Status.CLOSED:
                    print(
                        "Error: --verified-after-close requires a closed "
                        f"bead (currently {target.status.value}): {args.id}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                observed_since = current_instant()
            else:
                observed_since = resolve_observation_window_start()
            issue, changed = mutation.project.plus_one(
                args.id,
                args.note,
                reporter=reporter,
                refs=getattr(args, "ref", None) or (),
                observed_since=observed_since,
            )
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        reopen_withheld = bool(outcome.get("reopen_withheld"))
        reopen_withheld_closed_at = str(outcome.get("reopen_withheld_closed_at") or "")
        if changed and reopen_withheld:
            mutation.project.append_note(
                issue.id,
                _withheld_reopen_note(reporter, reopen_withheld_closed_at),
                author=reporter,
            )
        if changed:
            mutation.commit(require_mutation_commit_message("+1", [issue.id]))

    report_word = "report" if issue.plus_one_count == 1 else "reports"
    if changed and reopen_withheld:
        # Soft wrap: the reminder names two commands, and a mid-word wrap
        # (e.g. splitting `sase bead open`) reads as a broken instruction.
        Console(soft_wrap=True).print(
            f"[yellow]·[/yellow] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}, "
            f"but the close at {escape(reopen_withheld_closed_at)} was left "
            "standing (reopen withheld). Pass --verified-after-close if you "
            "reproduced this after the close, or `sase bead open` to reopen "
            "directly."
        )
        return
    if changed:
        Console().print(
            f"[green]✓[/green] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}"
        )
        return
    if reporter == issue.created_by:
        reason = "the task creator does not count as an additional reporter"
    else:
        reason = (
            f"{reporter} already reported this task; use `sase bead note` "
            "for supplementary evidence"
        )
    Console().print(
        f"[yellow]·[/yellow] Unchanged: {escape(issue.id)} — "
        f"{escape(reason)} ([bold]+{issue.plus_one_count}[/bold])"
    )


def handle_bead_note(args: argparse.Namespace) -> None:
    text = args.text
    if isinstance(text, list):
        text = " ".join(text)
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            author = args.author
            if author is None:
                author = resolve_mutation_author(mutation.project)
            issue = mutation.project.append_note(args.id, str(text), author=author)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("note", [issue.id]))
    print(f"Noted: {issue.id} — {issue.title}")
