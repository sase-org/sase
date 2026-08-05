"""Best-effort single-plan provenance refresh after a primary commit."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanHeaderRefreshOutcome:
    """Best-effort result of refreshing one committed plan's associations."""

    changed: bool = False
    committed: bool = False
    queued: bool = False
    skip_reason: str | None = None
    error: str | None = None


def refresh_committed_plan_header(
    commit_message: str,
    *,
    primary_root: Path | str,
    project: str | None = None,
) -> PlanHeaderRefreshOutcome:
    """Refresh the ``SASE_PLAN`` target after its primary commit exists.

    This projection is deliberately auxiliary: every failure is logged and
    returned to the caller, never raised across the primary commit boundary.
    """

    try:
        return _refresh_committed_plan_header(
            commit_message,
            primary_root=Path(primary_root).resolve(strict=False),
            project=project,
        )
    except Exception as exc:  # noqa: BLE001 - auxiliary post-commit boundary.
        _logger.warning("Could not refresh committed plan header: %s", exc)
        return PlanHeaderRefreshOutcome(error=str(exc) or type(exc).__name__)


def _refresh_committed_plan_header(
    commit_message: str,
    *,
    primary_root: Path,
    project: str | None,
) -> PlanHeaderRefreshOutcome:
    from sase.core.commit_footer_facade import parse_commit_footer

    footer = parse_commit_footer(commit_message)
    plan_ref = next(
        (tag.label for tag in footer.tags if tag.key == "PLAN"),
        None,
    )
    if not plan_ref:
        return PlanHeaderRefreshOutcome(skip_reason="commit has no SASE_PLAN tag")

    from sase.sdd.plan_refs import (
        canonicalize_plan_reference_from_roots,
        resolve_plan_reference_from_roots,
        workspace_context_for_plan_resolution,
    )
    from sase.sdd.store import resolve_sdd_store

    workspace_dir, workspace_num = workspace_context_for_plan_resolution(primary_root)
    store = resolve_sdd_store(workspace_dir, workspace_num)
    resolution = resolve_plan_reference_from_roots(
        plan_ref,
        roots=(store.kind_root("plans"),),
    )
    plan_path = resolution.resolved_path
    if plan_path is None:
        return PlanHeaderRefreshOutcome(
            skip_reason=f"plan reference could not be resolved: {plan_ref}"
        )
    canonical_ref = canonicalize_plan_reference_from_roots(
        plan_path,
        roots=(store.kind_root("plans"),),
    )
    if canonical_ref is None:
        return PlanHeaderRefreshOutcome(
            skip_reason=f"plan reference could not be normalized: {plan_ref}"
        )

    from sase.sdd._git_contention import store_git_write_lock

    plans_repo = store.repo_root_for_kind("plans")
    with store_git_write_lock(
        plans_repo,
        op="sdd.plan_header.post_commit",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            return PlanHeaderRefreshOutcome(error="plans store write lock is busy")

        from sase.sdd.associations import build_plan_association_index
        from sase.sdd.plan_header_writes import (
            refresh_association_sections,
            refresh_bead_plan_section,
            refresh_prompt_plan_section,
        )

        index = build_plan_association_index(
            store,
            primary_root=primary_root,
            project=project,
        )
        current = plan_path.read_text(encoding="utf-8")
        updated = refresh_bead_plan_section(
            current,
            store=store,
            primary_root=primary_root,
        )
        updated = refresh_prompt_plan_section(
            updated,
            source_path=plan_path,
            store=store,
            primary_root=primary_root,
            project=project,
        )
        updated = refresh_association_sections(
            updated,
            index.for_plan(canonical_ref),
        )
        from sase.file_references import format_with_prettier

        updated = format_with_prettier(updated)
        if updated == current:
            return PlanHeaderRefreshOutcome()
        plan_path.write_text(updated, encoding="utf-8")

        from sase.sdd.files import commit_sdd_store_files

        committed = commit_sdd_store_files(
            store,
            f"Refresh plan provenance for {plan_path.stem}",
            paths=[plan_path],
            push_after_commit="async",
            already_locked=True,
        )
        return PlanHeaderRefreshOutcome(changed=True, committed=committed)


__all__ = [
    "PlanHeaderRefreshOutcome",
    "refresh_committed_plan_header",
]
