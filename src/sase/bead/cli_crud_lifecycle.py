"""Open, close, and remove bead CLI command handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    resolve_bead_operation_context,
)
from sase.bead.cli_crud_common import (
    mutation_outcome_ids,
    print_attachment_echo_rows,
    resolve_mutation_author,
)
from sase.bead.epic_symbols import (
    raise_if_leftover_epic_symbols,
    raise_if_surviving_flag_definition,
)
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
from sase.cli_file_values import (
    CliFileValueError,
    read_at_path_value,
    read_note_text_value,
)

if TYPE_CHECKING:
    from sase.bead.attachments.authoring import AuthoredNoteAttachments
    from sase.bead.operation_context import BeadOperationContext


def handle_bead_open(args: argparse.Namespace) -> None:
    bead_context = resolve_bead_operation_context([args.id], for_write=True)
    issue_id = bead_context.resolved_ids[0]
    with bead_store_mutation(
        auto_commit_bead_store,
        bead_context=bead_context,
    ) as mutation:
        try:
            issue, reopened_ancestors = mutation.project.open(issue_id)
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


def _resolve_close_ids(
    ids: list[str],
    phases: list[str] | None,
    project: BeadProject,
) -> list[str]:
    if phases is None:
        return ids
    if len(ids) != 1:
        targets = ", ".join(ids)
        raise PhaseSelectorError(
            f"--phases takes exactly one epic bead ID (got {len(ids)}: {targets})"
        )
    phase_numbers = parse_phase_selectors(phases)
    return resolve_epic_phase_ids(project, ids[0], phase_numbers)


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


def _refuse_leftover_epic_symbols(
    project: BeadProject,
    issue_ids: list[str],
    *,
    start: Path | None = None,
) -> None:
    """Refuse a close that would stale remaining Justfile ``--epic-symbol`` entries."""
    issues = [project.show(issue_id) for issue_id in issue_ids]
    raise_if_leftover_epic_symbols(issues, start=start)
    raise_if_surviving_flag_definition(issues, start=start)


def _author_close_note(
    mutation: Any,
    resolved_ids: list[str],
    text: str,
    *,
    allow_sensitive: bool,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
) -> AuthoredNoteAttachments:
    """Run the attachment authoring service over a close note.

    The note is appended to every explicitly closed issue in one batch, so
    one roster — the union of every target's notes — feeds a single service
    run. Exits non-zero when the text has attachment problems; nothing is
    written then.
    """
    from sase.bead.attachments.authoring import (
        NoteAttachmentAuthoringError,
        author_note_attachments,
    )

    notes = []
    for resolved_id in resolved_ids:
        notes.extend(mutation.project.show(resolved_id).notes)
    from sase.bead.attachments.progress import transfer_progress

    try:
        return author_note_attachments(
            text,
            notes=notes,
            cwd=Path.cwd(),
            allow_sensitive=allow_sensitive,
            progress_factory=transfer_progress,
            audience_requested=audience_requested,
            audience_confirmed=audience_confirmed,
        )
    except NoteAttachmentAuthoringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def handle_bead_close(args: argparse.Namespace) -> None:
    allow_sensitive = bool(getattr(args, "allow_sensitive", False))
    local_only = bool(getattr(args, "local_only", False))
    from sase.bead.attachments import audience as _audience

    _private = bool(getattr(args, "private", False))
    _public = bool(getattr(args, "public", False))
    _confirmed = bool(getattr(args, "yes", False))
    _audience.validate_audience_flags(
        private=_private,
        public=_public,
        allow_sensitive=allow_sensitive,
        local_only=local_only,
        has_attachments=True,
    )
    audience_requested = _audience.requested_from_flags(
        private=_private, public=_public, local_only=local_only
    )
    audience_confirmed = _confirmed
    try:
        note = getattr(args, "note", None)
        if note is not None:
            note = read_note_text_value(note, target="--note", bead_id=args.ids[0])
        reason = getattr(args, "reason", None)
        if reason is not None:
            reason = read_at_path_value(reason, target="--reason")
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    phases = getattr(args, "phases", None)
    bead_context = resolve_bead_operation_context(args.ids, for_write=True)
    routed_ids = list(bead_context.resolved_ids)
    echo_rows: list[str] = []
    placement = "skip"
    placement_store: Any | None = None
    placement_key: str | None = None
    placement_require = False
    placement_wires: list[dict[str, Any]] = []
    with bead_store_mutation(
        auto_commit_bead_store,
        no_push=getattr(args, "no_push", False),
        bead_context=bead_context,
    ) as mutation:
        try:
            resolved_ids = _resolve_close_ids(routed_ids, phases, mutation.project)
            _refuse_leftover_epic_symbols(
                mutation.project,
                resolved_ids,
                start=_owner_symbol_start(bead_context),
            )
            author = resolve_mutation_author(mutation.project)
            note_attachments: list[dict[str, Any]] | None = None
            if note is not None:
                authored = _author_close_note(
                    mutation,
                    resolved_ids,
                    note,
                    allow_sensitive=allow_sensitive,
                    audience_requested=audience_requested,
                    audience_confirmed=audience_confirmed,
                )
                note = authored.stored_text
                note_attachments = authored.attachments or None
                echo_rows = authored.echo_rows
                if not note_attachments:
                    from sase.bead.attachments import audience as _echo_audience

                    echo_rows.extend(
                        _echo_audience.validate_audience_flags(
                            private=_private,
                            public=_public,
                            allow_sensitive=allow_sensitive,
                            local_only=local_only,
                            has_attachments=False,
                        )
                    )
                if note_attachments:
                    from sase.bead.attachments.upload import pre_write_upload

                    (
                        placement,
                        placement_store,
                        placement_key,
                        placement_require,
                    ) = pre_write_upload(
                        note_attachments,
                        echo_rows,
                        local_only=local_only,
                        bead_context=bead_context,
                    )
                    placement_wires = list(note_attachments)
            closed = mutation.project.close(
                resolved_ids,
                reason=reason,
                resolution=getattr(args, "resolution", None),
                force=getattr(args, "force", False),
                note=note,
                author=author,
                note_attachments=note_attachments,
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
        if placement in ("git", "large", "mixed", "public_pending") and placement_wires:
            from sase.bead.attachments.upload import post_write_queue

            post_write_queue(
                mutation,
                placement_wires,
                echo_rows,
                placement=placement,
                stores=placement_store,
                project_key=placement_key,
                require_upload=placement_require,
            )
        commit_message = close_mutation_commit_message(
            closed_ids=closed_ids,
            cascade_closed_ids=cascade_closed_ids,
            noted_ids=noted_ids,
        )
        if commit_message is not None:
            mutation.commit(commit_message)
    print_attachment_echo_rows(echo_rows)
    _settle_close_task_gates(
        closed,
        closed_ids,
        cascade_closed_ids,
        bead_context=bead_context,
    )
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
    *,
    bead_context: BeadOperationContext | None = None,
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

    project_name = (
        bead_context.project_key
        if bead_context is not None and bead_context.project_key
        else infer_project_name_from_cwd()
    )
    settle_closed_task_bead_gates(project_name, gateable_ids)


def _owner_symbol_start(
    bead_context: BeadOperationContext | None,
) -> Path | None:
    from sase.bead.operation_context import symbol_scan_start_for_operation_context

    return symbol_scan_start_for_operation_context(bead_context)


def handle_bead_rm(args: argparse.Namespace) -> None:
    bead_context = resolve_bead_operation_context(args.ids, for_write=True)
    issue_ids = list(bead_context.resolved_ids)
    with bead_store_mutation(
        auto_commit_bead_store,
        bead_context=bead_context,
    ) as mutation:
        try:
            removed = mutation.project.remove_many(issue_ids)
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
