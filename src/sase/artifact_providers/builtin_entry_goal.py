"""Python-owned resolution for ``@goal`` citations.

Rust parses and renders ``goal:<id>`` / ``goal:<project>@<id>`` and
deliberately returns ``unknown_kind`` for resolution: only Python holds the
ledger context (``resolve_goal_ledger`` + ``goal_ledger_show``). A citation
never binds; binding is G2's ``%goal``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    validate_builtin_entry,
)
from sase.artifact_ref_models import (
    ArtifactEntry,
    ArtifactRef,
    ArtifactRefContext,
)
from sase.artifact_ref_prompt_context import PromptRefContext


log = logging.getLogger(__name__)


def resolve_goal_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome | None:
    """Resolve ``@goal:<id>`` against the in-context project's ledger.

    Returns ``None`` only when the payload carries no id, so every
    well-formed ``goal:`` ref keeps Python-owned ``missing`` /
    ``unknown_project`` behavior instead of falling through to the Rust
    ``unknown_kind`` placeholder. An unknown id fails the launch, the same
    as other unresolved refs; citing a settled goal is allowed.
    """

    payload = reference.payload
    goal_id = payload.id or ""
    if not goal_id:
        return None
    project_key = _project_key(
        payload.project, context=context, ref_context=ref_context
    )
    if project_key is None:
        if payload.project is not None:
            known = ", ".join(sorted({project.key for project in context.projects}))
            return BuiltinEntryOutcome(
                status="unknown_project",
                diagnostic=(
                    f"unknown goal project {payload.project!r}"
                    + (f"; known projects: {known}" if known else "")
                ),
            )
        return BuiltinEntryOutcome(
            status="unknown_project",
            diagnostic=(
                "no project in context for "
                f"@{reference.rendered}; cite goal:<project>@{goal_id}"
            ),
        )

    try:
        from sase.goals.store import resolve_goal_ledger

        ledger = resolve_goal_ledger(project_key)
    except Exception as exc:
        log.debug("Unable to resolve goal ledger for %r", project_key, exc_info=True)
        return BuiltinEntryOutcome(
            status="missing",
            diagnostic=f"could not resolve the goal ledger for {project_key}: {exc}",
        )
    try:
        from sase.core.goal_ledger_facade import goal_ledger_show

        state = goal_ledger_show(ledger.root, goal_id)
    except Exception as exc:
        log.debug("Unable to show goal %r", goal_id, exc_info=True)
        return BuiltinEntryOutcome(
            status="missing",
            diagnostic=(
                f"unknown goal {goal_id} in project {ledger.project}; "
                "run `sase goal list` to see unsettled goals "
                f"({exc})"
            ),
        )

    status = str(state.get("status", "active"))
    title = str(state.get("title", goal_id))
    outcome = str(state.get("outcome", ""))
    entry = validate_builtin_entry(
        ArtifactEntry(
            stable_id=f"goal:{goal_id}",
            ref_kind="goal",
            canonical_argument=(
                f"{ledger.project}@{goal_id}"
                if payload.project is not None
                else goal_id
            ),
            display_label=title,
            origin="prompt_ref",
            project_display_name=ledger.project,
            properties={
                "id": goal_id,
                "status": status,
                "title": title,
                "outcome": outcome,
            },
        )
    )
    items_dir = ledger.root / "items" / goal_id
    return BuiltinEntryOutcome(
        status="exact",
        entry=entry,
        locator=reference.rendered,
        resolved_path=items_dir,
        canonical_reference=reference.rendered,
    )


def goal_now() -> str:
    """Return `now` as RFC3339 millis for card views."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project_key(
    explicit: str | None,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> str | None:
    if explicit is not None:
        folded = explicit.casefold()
        for project in context.projects:
            names = {project.name.casefold(), project.key.casefold()}
            names.update(alias.casefold() for alias in project.aliases)
            if folded in names:
                return project.key
        return None
    if ref_context.project is not None:
        return ref_context.project.key
    return context.selected_project


__all__ = ["goal_now", "resolve_goal_entry"]
