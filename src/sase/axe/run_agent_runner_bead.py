"""Post-preparation bead claims for the generic agent runner."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import Issue


def claim_bead_for_agent_launch(
    *,
    agent_name: str,
    bead_id: str,
    workspace_dir: str,
    workspace_num: int,
    artifacts_dir: str,
) -> Issue:
    """Claim *bead_id* after launch preparation and persist the mutation."""
    try:
        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead.sync import bead_store_write_lock
        from sase.sdd.store import ensure_sdd_kind_clone, resolve_sdd_store

        store = resolve_sdd_store(workspace_dir, workspace_num)
        beads_dir = store.kind_root("beads")
        if not beads_dir.is_dir():
            # A dedicated beads sidecar is materialized lazily, and the
            # provider workflow steps that clone it run after this claim.
            # Clone it here so the claim, its store lock, and its commit all
            # target a real repository.
            ensure_sdd_kind_clone(
                workspace_dir,
                workspace_num,
                "beads",
                strict=True,
            )
            store = resolve_sdd_store(workspace_dir, workspace_num)
            beads_dir = store.kind_root("beads")
            if not beads_dir.is_dir():
                raise RuntimeError(
                    "beads store could not be materialized for workspace "
                    f"#{workspace_num} at {beads_dir}"
                )

        # The mutation writes stream JSONL into a shared worktree, so it and
        # its commit hold one store-lock span: an integration that rebased
        # over the dirty mutation would discard the uncommitted claim.
        with bead_store_write_lock(beads_dir) as already_locked:
            with open_bead_project_for_beads_dir(beads_dir) as project:
                issue = project.claim_for_agent_launch(bead_id, agent_name)

            # In-tree bead mutations remain ordinary workspace edits that the
            # agent will commit with its implementation. Every managed
            # standalone SDD repository must durably record and synchronously
            # publish the claim before model execution.
            if not store.is_in_tree:
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
                        f"bead store mutation for {bead_id} produced no local "
                        "SDD commit"
                    )

        if not store.is_in_tree:
            from sase.bead.sync import publish_bead_claim

            publish_bead_claim(beads_dir, bead_id, agent_name)
        return issue
    except Exception as exc:
        raise RuntimeError(
            f"Failed to claim bead '{bead_id}' for agent '{agent_name}': {exc}"
        ) from exc


__all__ = ["claim_bead_for_agent_launch"]
