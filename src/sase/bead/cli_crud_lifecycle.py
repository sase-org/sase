"""Open, close, and remove bead CLI command handlers."""

from __future__ import annotations

import argparse
import sys

from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
from sase.bead.cli_crud_common import mutation_outcome_ids, resolve_mutation_author
from sase.bead.epic_symbols import raise_if_leftover_epic_symbols
from sase.bead.model import Issue, IssueType
from sase.bead.mutation_commit import (
    close_mutation_commit_message,
    require_mutation_commit_message,
)
from sase.bead.phase_selector import (
    PhaseSelectorError,
    parse_phase_selectors,
    resolve_epic_phase_ids,
)
from sase.bead.project import BeadProject
from sase.cli_file_values import CliFileValueError, read_at_path_value


def handle_bead_open(args: argparse.Namespace) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            issue, reopened_ancestors = mutation.project.open(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("open", [issue.id]))
    print(f"○ Opened: {issue.id} — {issue.title}")
    for ancestor in reopened_ancestors:
        print(f"○ Reopened ancestor: {ancestor.id} — {ancestor.title}")


def _resolve_close_ids(args: argparse.Namespace, project: BeadProject) -> list[str]:
    phases = getattr(args, "phases", None)
    if phases is None:
        return args.ids
    if len(args.ids) != 1:
        targets = ", ".join(args.ids)
        raise PhaseSelectorError(
            f"--phases takes exactly one epic bead ID (got {len(args.ids)}: {targets})"
        )
    phase_numbers = parse_phase_selectors(phases)
    return resolve_epic_phase_ids(project, args.ids[0], phase_numbers)


def _print_close_results(
    issues: list[Issue],
    *,
    closed_ids: list[str],
    already_closed_ids: list[str],
    noted_ids: list[str],
    cascade_closed_ids: list[str],
) -> None:
    closed = set(closed_ids)
    already_closed = set(already_closed_ids)
    noted = set(noted_ids)
    cascade_closed = set(cascade_closed_ids)

    for issue in issues:
        if issue.id in cascade_closed:
            _print_close_result_row("↳", "Closed", issue)
        elif issue.id in closed:
            _print_close_result_row("✓", "Closed", issue)
        elif issue.id in already_closed:
            resolution = issue.resolution.value if issue.resolution else "(unrecorded)"
            metadata = f" ({issue.closed_at or 'unknown close time'} · {resolution})"
            _print_close_result_row("·", "Already closed", issue, metadata)

        if issue.id in noted:
            _print_close_result_row("+", "Noted", issue)


def _print_close_result_row(
    glyph: str,
    label: str,
    issue: Issue,
    suffix: str = "",
) -> None:
    prefix = f"{glyph} {label}"
    print(f"{prefix:<18}{issue.id} — {issue.title}{suffix}")


def _refuse_leftover_epic_symbols(project: BeadProject, issue_ids: list[str]) -> None:
    """Refuse a close that would stale remaining Justfile ``--epic-symbol`` entries."""
    issues = [project.show(issue_id) for issue_id in issue_ids]
    raise_if_leftover_epic_symbols(issues)


def handle_bead_close(args: argparse.Namespace) -> None:
    try:
        note = getattr(args, "note", None)
        if note is not None:
            note = read_at_path_value(note, target="--note")
        reason = getattr(args, "reason", None)
        if reason is not None:
            reason = read_at_path_value(reason, target="--reason")
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    with bead_store_mutation(
        auto_commit_bead_store,
        no_push=getattr(args, "no_push", False),
    ) as mutation:
        try:
            resolved_ids = _resolve_close_ids(args, mutation.project)
            _refuse_leftover_epic_symbols(mutation.project, resolved_ids)
            author = None
            if note is not None:
                author = resolve_mutation_author(mutation.project)
            closed = mutation.project.close(
                resolved_ids,
                reason=reason,
                resolution=getattr(args, "resolution", None),
                force=getattr(args, "force", False),
                note=note,
                author=author,
            )
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except PhaseSelectorError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        closed_ids = mutation_outcome_ids(outcome, "closed_ids")
        already_closed_ids = mutation_outcome_ids(outcome, "already_closed_ids")
        noted_ids = mutation_outcome_ids(outcome, "noted_ids")
        cascade_closed_ids = mutation_outcome_ids(outcome, "cascade_closed_ids")
        commit_message = close_mutation_commit_message(
            closed_ids=closed_ids,
            cascade_closed_ids=cascade_closed_ids,
            noted_ids=noted_ids,
        )
        if commit_message is not None:
            mutation.commit(commit_message)
    _settle_close_task_gates(closed, closed_ids, cascade_closed_ids)
    _print_close_results(
        closed,
        closed_ids=closed_ids,
        already_closed_ids=already_closed_ids,
        noted_ids=noted_ids,
        cascade_closed_ids=cascade_closed_ids,
    )


def _settle_close_task_gates(
    issues: list[Issue],
    closed_ids: list[str],
    cascade_closed_ids: list[str],
) -> None:
    """Cancel each just-closed task or flag bead's pending gate, skipping others.

    Every plan/phase close and every already-closed no-op has no candidate
    ids here, so it costs nothing beyond building and checking this set.
    """
    candidate_ids = set(closed_ids) | set(cascade_closed_ids)
    if not candidate_ids:
        return
    gateable_ids = {
        issue.id
        for issue in issues
        if issue.id in candidate_ids and issue.issue_type is IssueType.TASK
    }
    if not gateable_ids:
        return
    from sase.bead.close_gate_settle import settle_closed_task_bead_gates
    from sase.bead.project_name import infer_project_name_from_cwd

    settle_closed_task_bead_gates(infer_project_name_from_cwd(), gateable_ids)


def handle_bead_rm(args: argparse.Namespace) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            removed = mutation.project.remove_many(args.ids)
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(
            require_mutation_commit_message("rm", [issue.id for issue in removed])
        )
    for issue in removed:
        print(f"✗ Removed: {issue.id} — {issue.title}")
