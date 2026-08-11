"""Python-owned short-id resolution for ``@bead``.

Per ``sase/memory/sase_beads.md``, a short bead id is the suffix after the
final dash (``js.4`` for ``sase-js.4``). A full id (containing a dash) is
left entirely to the unchanged Rust resolver: this module only widens what a
*short* id can mean.
"""

from __future__ import annotations

from dataclasses import replace
import logging

from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    validate_builtin_entry,
)
from sase.artifact_ref_models import (
    ArtifactEntry,
    ArtifactRef,
    ArtifactRefBeadStore,
    ArtifactRefContext,
)
from sase.artifact_ref_operations import render_artifact_ref, resolve_artifact_ref
from sase.artifact_ref_prompt_context import PromptRefContext


log = logging.getLogger(__name__)


def resolve_bead_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome | None:
    """Resolve a short bead id against the in-context store, then any other.

    Returns ``None`` for a full id or when no store resolves the shorthand,
    so a full id and an unresolvable short id both keep today's Rust-only
    ``missing``/``unknown_project`` behavior exactly.
    """

    payload = reference.payload
    short_id = payload.id or ""
    if not short_id or "-" in short_id:
        return None

    resolved: list[tuple[ArtifactRefBeadStore, str]] = []
    for store in _ordered_bead_stores(context, ref_context):
        try:
            from sase.core.bead_read_facade import resolve_id

            full_id = resolve_id(store.root, short_id)
        except KeyError:
            continue
        except ValueError as exc:
            # A single store's own shorthand is ambiguous; surface verbatim.
            return BuiltinEntryOutcome(status="ambiguous", diagnostic=str(exc))
        resolved.append((store, full_id))

    if not resolved:
        return None
    if len(resolved) > 1:
        candidates = tuple(f"{store.project}: {full_id}" for store, full_id in resolved)
        return BuiltinEntryOutcome(
            status="ambiguous",
            candidates=candidates,
            diagnostic=(
                f"@bead:{short_id} is ambiguous across projects; candidates: "
                f"{', '.join(candidates)}"
            ),
        )

    store, full_id = resolved[0]
    rewritten = replace(reference, payload=replace(payload, id=full_id))
    resolution = resolve_artifact_ref(rewritten, context=context)

    return BuiltinEntryOutcome(
        status=resolution.status,
        entry=_bead_entry(store, full_id),
        locator=resolution.locator,
        resolved_path=resolution.resolved_path,
        candidates=resolution.candidates,
        diagnostic=resolution.diagnostic,
        canonical_reference=render_artifact_ref(rewritten),
    )


def _ordered_bead_stores(
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> tuple[ArtifactRefBeadStore, ...]:
    project = None if ref_context.project is None else ref_context.project.display_name
    if project is None:
        return context.bead_stores
    own = tuple(store for store in context.bead_stores if store.project == project)
    rest = tuple(store for store in context.bead_stores if store.project != project)
    return own + rest


def _bead_entry(store: ArtifactRefBeadStore, full_id: str) -> ArtifactEntry | None:
    properties = {"project": store.project, "id": full_id}
    try:
        from sase.core.bead_read_facade import show

        issue = show(store.root, full_id)
    except Exception:
        log.debug("Unable to load bead %r for entry properties", full_id, exc_info=True)
    else:
        properties["title"] = issue.title
        properties["type"] = issue.issue_type.value
        properties["status"] = issue.status.value
        if issue.tier is not None:
            properties["tier"] = issue.tier.value
        if issue.size is not None:
            properties["size"] = issue.size.value
        if issue.parent_id:
            properties["parent"] = issue.parent_id
        if issue.assignee:
            properties["assignee"] = issue.assignee

    return validate_builtin_entry(
        ArtifactEntry(
            stable_id=f"bead:{full_id}",
            ref_kind="bead",
            canonical_argument=full_id,
            display_label=full_id,
            origin="prompt_ref",
            project_display_name=store.project,
            properties=properties,
        )
    )


__all__ = ["resolve_bead_entry"]
