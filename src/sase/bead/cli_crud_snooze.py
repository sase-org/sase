"""Snooze and wake bead CLI command handler."""

from __future__ import annotations

import argparse
import getpass
import sys

from rich.console import Console
from rich.markup import escape

from sase.agent.identity import discover_agent_identity
from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
from sase.bead.model import Issue
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.bead.project import BeadProject
from sase.bead.snooze_presentation import (
    SNOOZE_ACCENT,
    SNOOZE_GLYPH,
    snooze_plus_one_label,
    snooze_summary,
)
from sase.bead.snooze_time import (
    ACCEPTED_SNOOZE_FORMS,
    SnoozeTimeError,
    parse_snooze_until,
)
from sase.cli_file_values import CliFileValueError, read_at_path_value


def _snooze_actor(project: BeadProject) -> str:
    """Resolve who to attribute a snooze to, never blank.

    The store rejects an unattributed snooze, so this falls through the acting
    agent, the configured store owner, and finally the local user rather than
    failing a mutation over missing configuration.
    """
    identity = discover_agent_identity()
    if identity is not None:
        return identity.name
    return project.owner.strip() or getpass.getuser()


def handle_bead_snooze(args: argparse.Namespace) -> None:
    """Defer task beads until a wake time, or wake them early."""
    cancel = bool(getattr(args, "cancel", False))
    until_arg = getattr(args, "until", None)
    plus_ones = getattr(args, "plus_ones", None)
    raw_reason = getattr(args, "reason", None) or ""
    if cancel and (until_arg or plus_ones is not None or raw_reason):
        print(
            "Error: --cancel takes no wake conditions; drop -u/-p/-r",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cancel and not until_arg:
        print(
            f"Error: -u/--until is required; expected {ACCEPTED_SNOOZE_FORMS}",
            file=sys.stderr,
        )
        sys.exit(1)
    if plus_ones is not None and plus_ones <= 0:
        print("Error: -p/--plus-ones must be a positive count", file=sys.stderr)
        sys.exit(1)

    until = ""
    if until_arg:
        try:
            until = parse_snooze_until(until_arg)
        except SnoozeTimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    try:
        reason = read_at_path_value(raw_reason, target="--reason") if raw_reason else ""
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        actor = _snooze_actor(proj)
        # Resolve every id before mutating any bead, so a typo in the last
        # argument cannot leave the first half of the batch snoozed.
        resolved_ids: list[str] = []
        for raw_id in args.ids:
            try:
                resolved_ids.append(proj.show(raw_id).id)
            except KeyError:
                print(f"Error: issue not found: {raw_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        issues: list[Issue] = []
        for issue_id in resolved_ids:
            try:
                if cancel:
                    issues.append(proj.cancel_snooze(issue_id, actor=actor))
                else:
                    issues.append(
                        proj.snooze(
                            issue_id,
                            until=until,
                            plus_ones=plus_ones,
                            reason=reason,
                            actor=actor,
                        )
                    )
            except KeyError:
                print(f"Error: issue not found: {issue_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        mutation.commit(
            require_mutation_commit_message(
                "snooze_cancel" if cancel else "snooze",
                [issue.id for issue in issues],
            )
        )
    # Soft wrap: a confirmation naming an absolute time, a relative time, and
    # a +1 target is easily wider than 80 columns, and a wrapped one reads as
    # two unrelated lines.
    console = Console(soft_wrap=True)
    for issue in issues:
        console.print(_snooze_result_line(issue, canceled=cancel))


def _snooze_result_line(issue: Issue, *, canceled: bool) -> str:
    """Render one confirmation naming both wake conditions in Rich markup."""
    if canceled or issue.snooze is None:
        return f"[green]○[/green] Woken: {escape(issue.id)} — {escape(issue.title)}"
    line = (
        f"[{SNOOZE_ACCENT}]{SNOOZE_GLYPH}[/{SNOOZE_ACCENT}] Snoozed "
        f"[bold]{escape(issue.id)}[/bold] "
        f"{escape(snooze_summary(issue.snooze))}"
    )
    if plus_one := snooze_plus_one_label(issue):
        line += f" [dim]·[/dim] wakes early at {escape(plus_one)}"
    return line
