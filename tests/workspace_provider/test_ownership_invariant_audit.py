"""End-to-end ownership invariant audit and regression gates (sase-mq.7).

Phases 1-6 unit-test their own primitives in isolation (see
``test_workspace_ownership.py``, ``test_workspace_lease.py``,
``test_reset_replay.py``, ``tests/test_bead/test_background_store.py``, and
``tests/test_sidecar_auto_sync.py``). Plan approval, epic launch, task
launch, and external-issue-mirror flows have their own dedicated ownership
coverage in those phases' test suites and are not re-tested here.

This module's job is the cross-cutting regression gate the epic's final
phase asks for: combine several of those primitives against *one* shared
primary checkout and assert byte-for-byte primary immutability (HEAD, refs,
and tracked-file content) across the combination, not just within one
primitive's own unit tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
    WorkspaceOwnershipError,
    authorize_store_mutation,
)
from sase.workspace_provider.reset_replay import ReplayConflict, reset_and_replay
from sase._sidecar_auto_sync import sync_primary_sidecar_role
from sase._linked_repo_config import _SIDECAR_REMOTE_URL_KEY, _SIDECAR_ROLE_KEY

from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

PrimarySnapshot = tuple[str, str, str]


def _snapshot(repo: Path) -> PrimarySnapshot:
    """Capture HEAD, every ref, and the tracked-content diff against HEAD.

    HEAD/refs catch any commit, branch, or ref mutation. The ``diff HEAD``
    stat catches any staged or unstaged change to a tracked file without
    tripping on unrelated untracked directories (such as a sidecar clone
    nested under the checkout), matching the ownership boundary this audit
    verifies: primary worktree/index/HEAD/refs, not arbitrary disk state.
    """

    head = git(["rev-parse", "HEAD"], repo).stdout.strip()
    refs = git(["show-ref"], repo).stdout
    diff = git(["diff", "HEAD", "--stat"], repo).stdout
    return head, refs, diff


def _init_primary(
    tmp_path: Path, *, origin_name: str = "origin.git"
) -> tuple[Path, Path]:
    """Return ``(primary, origin)`` for a primary checkout with one commit."""

    origin = tmp_path / origin_name
    primary = tmp_path / "proj"
    init_bare_repo(origin)
    clone(origin, primary)
    (primary / "README.md").write_text("v1\n", encoding="utf-8")
    commit_all(primary, "init")
    git(["push", "-u", "origin", "main"], primary)
    return primary, origin


def _write_project_file(path: Path, *, primary: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"WORKSPACE_DIR: {primary}\nNAME: demo\nDESCRIPTION:\n  fixture\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    return path


def _leased_context(checkout: Path, primary: Path) -> OperationContext:
    return OperationContext(
        project="demo",
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=10,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        project_file=None,
        claim_pid=1,
        claim_workflow="chop:demo",
    )


class TestMachineMutationAndConflictRecoveryRefusePrimary:
    def test_authorize_store_mutation_refuses_primary_and_leaves_it_untouched(
        self, tmp_path: Path
    ) -> None:
        primary, _ = _init_primary(tmp_path)
        (primary / ".sase").mkdir(parents=True, exist_ok=True)
        (primary / ".sase" / "sdd-store.json").write_text("{}", encoding="utf-8")
        before = _snapshot(primary)

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            authorize_store_mutation(
                primary / ".sase" / "sdd",
                mutation_origin="machine",
            )

        assert _snapshot(primary) == before

    def test_reset_and_replay_refuses_primary_and_leaves_it_untouched(
        self, tmp_path: Path
    ) -> None:
        primary, _ = _init_primary(tmp_path)
        before = _snapshot(primary)
        context = OperationContext(
            project="demo",
            access_kind=AccessKind.LEASED_OPERATIONAL,
            mutation_origin=MutationOrigin.MACHINE,
            workspace_num=0,
            checkout_dir=primary,
            primary_checkout_dir=primary,
        )

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            reset_and_replay(context, primary, lambda: "ok")

        assert _snapshot(primary) == before


class TestLeasedConflictRecoveryLeavesPrimaryUntouched:
    def test_lease_reset_and_replay_recovers_in_leased_checkout_only(
        self, tmp_path: Path
    ) -> None:
        primary, origin = _init_primary(tmp_path)
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        checkout = tmp_path / "proj_10"
        clone(origin, checkout)

        # Advance the shared remote (as if another publisher landed a change)
        # so the leased checkout's replay must reset to the new tip.
        (primary / "README.md").write_text("v2\n", encoding="utf-8")
        commit_all(primary, "advance")
        git(["push"], primary)
        primary_snapshot_after_advance = _snapshot(primary)

        context = _leased_context(checkout, primary)
        lease = OperationalLease(
            project="demo",
            workflow="chop:demo",
            holder="axe",
            workspace_num=10,
            checkout_dir=checkout,
            project_file=project_file,
            claim_pid=1,
            cl_name="axe",
            context=context,
        )
        attempts = 0

        def _operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ReplayConflict("stale local branch")
            return "recovered"

        result = lease.reset_and_replay(_operation)

        assert result.value == "recovered"
        assert result.reset_performed is True
        assert attempts == 2
        assert (
            git(["rev-parse", "HEAD"], checkout).stdout.strip()
            == git(["rev-parse", "HEAD"], origin).stdout.strip()
        )
        # The leased checkout converged; the primary checkout that produced
        # the advance is untouched by the recovery it triggered downstream.
        assert _snapshot(primary) == primary_snapshot_after_advance


class TestSidecarAutoSyncLeavesPrimaryUntouched:
    def _entry(self, role: str, *, remote_url: str) -> dict[str, Any]:
        return {
            _SIDECAR_ROLE_KEY: role,
            "auto_sync": True,
            "disabled": False,
            _SIDECAR_REMOTE_URL_KEY: remote_url,
        }

    def test_clean_behind_sidecar_fast_forwards_without_touching_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase._sidecar_auto_sync as sidecar_auto_sync

        primary, _ = _init_primary(tmp_path)
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        before = _snapshot(primary)

        sidecar_remote = tmp_path / "plans.git"
        seed = tmp_path / "plans-seed"
        sidecar = primary / "sase" / "repos" / "plans"
        init_bare_repo(sidecar_remote)
        clone(sidecar_remote, seed)
        (seed / "plan.md").write_text("v1\n", encoding="utf-8")
        commit_all(seed, "v1")
        git(["push", "-u", "origin", "main"], seed)
        clone(sidecar_remote, sidecar)
        (seed / "plan.md").write_text("v2\n", encoding="utf-8")
        commit_all(seed, "v2")
        git(["push"], seed)
        new_head = git(["rev-parse", "HEAD"], seed).stdout.strip()

        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [self._entry("plans", remote_url=str(sidecar_remote))],
        )

        result = sync_primary_sidecar_role(
            "demo",
            "plans",
            project_file=project_file,
            config={"workspace": {"root": "adjacent", "project_key": "demo"}},
        )

        assert result.status == "refreshed"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == new_head
        assert _snapshot(primary) == before

    def test_dirty_sidecar_is_preserved_and_primary_is_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase._sidecar_auto_sync as sidecar_auto_sync

        primary, _ = _init_primary(tmp_path)
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        before = _snapshot(primary)

        sidecar_remote = tmp_path / "plans.git"
        sidecar = primary / "sase" / "repos" / "plans"
        init_bare_repo(sidecar_remote)
        clone(sidecar_remote, sidecar)
        (sidecar / "plan.md").write_text("v1\n", encoding="utf-8")
        commit_all(sidecar, "v1")
        git(["push", "-u", "origin", "main"], sidecar)
        dirty_head = git(["rev-parse", "HEAD"], sidecar).stdout.strip()
        (sidecar / "plan.md").write_text("local edit\n", encoding="utf-8")

        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [self._entry("plans", remote_url=str(sidecar_remote))],
        )

        result = sync_primary_sidecar_role(
            "demo",
            "plans",
            project_file=project_file,
            config={"workspace": {"root": "adjacent", "project_key": "demo"}},
        )

        assert result.status == "dirty"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == dirty_head
        assert (sidecar / "plan.md").read_text(encoding="utf-8") == "local edit\n"
        assert _snapshot(primary) == before
