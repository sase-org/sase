"""Off-thread write tasks for the Snippets panel.

Every function here mutates disk or reloads a catalog and must only ever
run inside a session worker, never on the event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.tui.actions.proc_actions import TrackedProcResult
from sase.ace.tui.prompt_catalog import compose_pending_snippet_saves
from sase.ace.tui.snippets_panel_catalog import (
    SnippetProjectRef,
    SnippetProjectSnapshot,
    invalidate_snippet_project,
    load_snippet_project_snapshot,
)
from sase.snippet.lookup import SnippetLookupError
from sase.snippet.models import SnippetMutationOutcome
from sase.snippet.mutation import (
    SnippetConflictError,
    SnippetMutationError,
    SnippetReadOnlyError,
    SnippetValidationError,
    add_snippet,
    delete_snippet,
    update_snippet,
)
from sase.xprompt.write_targets import (
    PostWriteActionOffer,
    XPromptWriteTarget,
    build_post_write_action_offers,
    classify_written_file,
)

SnippetWriteKind = Literal["add", "edit", "delete"]


@dataclass(frozen=True, slots=True)
class SnippetWritePayload:
    """Outcome of one Snippets-panel create/update/delete worker."""

    kind: SnippetWriteKind
    error: str | None = None
    outcome: SnippetMutationOutcome | None = None
    snapshot: SnippetProjectSnapshot | None = None
    preferred_trigger: str | None = None
    pending_saves: dict[str, str] | None = None
    composed_snippets: dict[str, str] | None = None
    offers: tuple[PostWriteActionOffer, ...] = ()
    write_target: XPromptWriteTarget | None = None
    draft_trigger: str | None = None
    draft_template: str | None = None
    draft_target: str | None = None
    draft_digest: str | None = None
    draft_force: bool = False
    draft_mode: SnippetWriteKind | None = None


def run_snippets_panel_write(
    *,
    kind: SnippetWriteKind,
    project: SnippetProjectRef,
    trigger: str,
    template: str = "",
    target: str | None = None,
    expected_digest: str | None = None,
    force: bool = False,
    preferred_trigger: str | None = None,
    pending_saves: dict[str, str] | None = None,
) -> TrackedProcResult[SnippetWritePayload]:
    """Apply one add/edit/delete and reload that project's snapshot."""
    try:
        if kind == "add":
            outcome = add_snippet(
                project.key,
                trigger,
                template,
                target=target,
                force=force,
                expected_digest=expected_digest,
            )
        elif kind == "edit":
            outcome = update_snippet(
                project.key,
                trigger,
                template,
                target=target,
                expected_digest=expected_digest,
            )
        else:
            outcome = delete_snippet(
                project.key,
                trigger,
                expected_digest=expected_digest,
            )
    except SnippetValidationError as exc:
        return TrackedProcResult(
            False,
            _validation_message(exc),
            payload=SnippetWritePayload(kind=kind, error="validation"),
        )
    except SnippetConflictError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=SnippetWritePayload(
                kind=kind,
                error="conflict",
                draft_trigger=trigger,
                draft_template=template,
                draft_target=target,
                draft_digest=expected_digest,
                draft_force=force,
                draft_mode=kind,
            ),
        )
    except SnippetReadOnlyError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=SnippetWritePayload(kind=kind, error="readonly"),
        )
    except (SnippetMutationError, SnippetLookupError) as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=SnippetWritePayload(kind=kind, error="other"),
        )

    invalidate_snippet_project(project.key)
    snapshot = load_snippet_project_snapshot(project)
    pending = dict(pending_saves or {})
    if kind == "delete":
        pending.pop(outcome.trigger, None)
    else:
        pending[outcome.trigger] = outcome.template
    composed = _compose_pending(snapshot, pending)
    write_target = XPromptWriteTarget(
        read_path=Path(outcome.read_path),
        write_path=Path(outcome.write_path),
        apply_target=(
            None if outcome.apply_target is None else Path(outcome.apply_target)
        ),
        via_chezmoi=outcome.via_chezmoi,
    )
    kind_label = classify_written_file(
        write_target.write_path, read_path=write_target.read_path
    )
    offers = build_post_write_action_offers(
        write_target,
        kind=kind_label,
        is_new=outcome.created,
        xprompt_name=outcome.trigger,
        noun="snippet",
        commit_type="snippet",
    )
    selected = preferred_trigger if kind == "delete" else outcome.trigger
    return TrackedProcResult(
        True,
        _success_message(kind, outcome),
        payload=SnippetWritePayload(
            kind=kind,
            outcome=outcome,
            snapshot=snapshot,
            preferred_trigger=selected,
            pending_saves=pending,
            composed_snippets=composed,
            offers=offers,
            write_target=write_target,
        ),
    )


def _compose_pending(
    snapshot: SnippetProjectSnapshot, pending: dict[str, str]
) -> dict[str, str]:
    base = (
        dict(snapshot.catalog.explicit_templates)
        if snapshot.catalog is not None
        else {}
    )
    if not pending:
        catalog = snapshot.catalog
        return dict(catalog.composed_templates) if catalog is not None else base
    return compose_pending_snippet_saves(base, pending)


def _success_message(kind: SnippetWriteKind, outcome: SnippetMutationOutcome) -> str:
    project = outcome.project_name or "the project"
    if kind == "delete":
        revealed = ""
        if outcome.revealed is not None:
            source = (
                outcome.revealed.origin.display_path or outcome.revealed.origin.kind
            )
            revealed = f" Revealed {source}."
        return (
            f'Deleted "{outcome.trigger}" from {project}.{revealed} '
            f"Restore with: {outcome.restore_command}"
        )
    verb = {"created": "Added", "replaced": "Updated", "shadowed": "Shadowed"}.get(
        outcome.action, "Saved"
    )
    return f'{verb} "{outcome.trigger}" in {project}.'


def _validation_message(exc: SnippetValidationError) -> str:
    if not exc.diagnostics:
        return str(exc)
    first = exc.diagnostics[0]
    return f"{first.code}: {first.message}"


__all__ = [
    "SnippetWriteKind",
    "SnippetWritePayload",
    "run_snippets_panel_write",
]
