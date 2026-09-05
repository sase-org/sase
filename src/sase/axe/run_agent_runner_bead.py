"""Post-preparation bead claims for the generic agent runner."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import Issue

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def _is_missing_issue_error(exc: BaseException) -> bool:
    return isinstance(exc, KeyError) and "Issue not found:" in str(exc)


def _ready_launch_beads_store(
    workspace_dir: str,
    workspace_num: int,
    *,
    fresh: bool = False,
) -> tuple[SddStore, Path]:
    from sase.sdd.store import ensure_sdd_kind_clone, resolve_sdd_store

    ensure_sdd_kind_clone(
        workspace_dir,
        workspace_num,
        "beads",
        strict=True,
        fresh=fresh,
    )
    store = resolve_sdd_store(workspace_dir, workspace_num)
    beads_dir = store.kind_root("beads")
    if not beads_dir.is_dir():
        raise RuntimeError(
            "beads store could not be materialized for workspace "
            f"#{workspace_num} at {beads_dir}"
        )
    return store, beads_dir


def claim_bead_for_agent_launch(
    *,
    agent_name: str,
    bead_id: str,
    workspace_dir: str,
    workspace_num: int,
    artifacts_dir: str,
    force_reuse_prior_owner: str | None = None,
) -> Issue:
    """Claim *bead_id* after launch preparation and persist the mutation."""
    try:
        from sase.bead.force_reuse import (
            issue_is_in_progress_for_another_agent,
            issue_retains_force_reuse_owner,
        )
        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead.sync import bead_store_write_lock

        # Heal a missing, torn, or stale beads sidecar before the claim
        # reads it. Recovery takes the same store git write lock and defers
        # on contention, so this must run outside `bead_store_write_lock`.
        store, beads_dir = _ready_launch_beads_store(
            workspace_dir,
            workspace_num,
        )

        def _claim_locked_span() -> tuple[Issue, bool]:
            # The mutation writes stream JSONL into a shared worktree, so it
            # and its commit hold one store-lock span: an integration that
            # rebased over the dirty mutation would discard the uncommitted
            # claim.
            with bead_store_write_lock(beads_dir) as already_locked:
                with open_bead_project_for_beads_dir(beads_dir) as project:
                    current_issue = project.show(bead_id)
                    if (
                        force_reuse_prior_owner is not None
                        and issue_retains_force_reuse_owner(
                            current_issue,
                            agent_name=agent_name,
                            prior_owner=force_reuse_prior_owner,
                        )
                    ):
                        claimed = current_issue
                        mutated = False
                    else:
                        if issue_is_in_progress_for_another_agent(
                            current_issue,
                            agent_name=agent_name,
                        ):
                            raise RuntimeError(
                                f"bead '{bead_id}' is already in_progress and "
                                f"assigned to '{current_issue.assignee}'"
                            )
                        claimed = project.claim_for_agent_launch(bead_id, agent_name)
                        mutated = project.mutation_changed

                # In-tree bead mutations remain ordinary workspace edits that
                # the agent will commit with its implementation. Every managed
                # standalone SDD repository must durably record and
                # synchronously publish the claim before model execution.
                if mutated and not store.is_in_tree:
                    from sase.sdd.files import commit_sdd_store_files

                    committed = commit_sdd_store_files(
                        store,
                        f"chore(beads): claim {bead_id} for {agent_name}",
                        auto_commit_type="beads",
                        paths=[beads_dir],
                        push_after_commit=False,
                        artifacts_dir=Path(artifacts_dir),
                        already_locked=already_locked,
                    )
                    if not committed:
                        raise RuntimeError(
                            f"bead store mutation for {bead_id} produced no "
                            "local SDD commit"
                        )
            return claimed, mutated

        try:
            issue, changed = _claim_locked_span()
        except KeyError as exc:
            if not _is_missing_issue_error(exc):
                raise
            store, beads_dir = _ready_launch_beads_store(
                workspace_dir,
                workspace_num,
                fresh=True,
            )
            issue, changed = _claim_locked_span()

        if changed and not store.is_in_tree:
            from sase.bead.sync import publish_bead_claim

            publish_bead_claim(beads_dir, bead_id, agent_name)
            _schedule_launch_claim_convergence(workspace_dir)
        return issue
    except Exception as exc:
        raise RuntimeError(
            f"Failed to claim bead '{bead_id}' for agent '{agent_name}': {exc}"
        ) from exc


def _schedule_launch_claim_convergence(workspace_dir: str) -> None:
    """Hint primary-sidecar sync after a published launch claim."""

    from sase.bead.background_store import schedule_beads_sidecar_convergence
    from sase.workspace_provider.marker import find_marker_from_cwd

    try:
        found = find_marker_from_cwd(workspace_dir)
    except Exception:
        return
    if found is None:
        return
    _checkout, marker = found
    project = marker.project_name or marker.project_key
    if project:
        schedule_beads_sidecar_convergence(project)


__all__ = ["claim_bead_for_agent_launch"]
