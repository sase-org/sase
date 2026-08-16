"""End-to-end ownership invariant audit and regression gates (sase-mq.7/mq.8).

Phases 1-6 unit-test their own primitives in isolation (see
``test_workspace_ownership.py``, ``test_workspace_lease.py``,
``test_reset_replay.py``, ``tests/test_bead/test_background_store.py``, and
``tests/test_sidecar_auto_sync.py``). Plan approval/archive, epic launch,
task launch, and external-issue-mirror flows also have focused unit coverage;
the audit here verifies those workflows against the shared primary immutability
contract.

This module's job is the cross-cutting regression gate the epic's final
phase asks for: combine several of those primitives against *one* shared
primary checkout and assert byte-for-byte primary immutability (HEAD, refs,
index, primary-owned files, and operation markers) across the combination,
not just within one primitive's own unit tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase._plan_archive_approval import archive_approved_plan
from sase.bead.epic_launch import start_epic_launch_monitor
from sase.bead.task_launch import submit_task_launch_task
from sase.workspace_provider.lease import (
    OperationalLease,
    _OperationalLeaseError as OperationalLeaseError,
)
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
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger

from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo
from tests.sdd_policy_helpers import patched_sdd_policy
from tests.workspace_lease_helpers import (
    fake_operational_lease,
    patched_operational_lease,
)


@dataclass(frozen=True)
class PrimarySnapshot:
    head: str
    refs: str
    index: str
    staged_diff: str
    worktree_diff: str
    owned_files: tuple[tuple[str, bytes], ...]
    operation_markers: tuple[tuple[str, bytes | None], ...]


def _snapshot(repo: Path) -> PrimarySnapshot:
    """Capture primary-owned worktree, index, HEAD, refs, and markers.

    Sidecar clones under ``sase/repos`` are intentionally excluded: those
    repositories are distinct SDD stores nested under the checkout directory,
    and the ownership invariant permits conservative syncs there. Everything
    else outside ``.git`` is treated as primary-owned filesystem state.
    """

    return PrimarySnapshot(
        head=git(["rev-parse", "HEAD"], repo).stdout.strip(),
        refs=git(["show-ref"], repo).stdout,
        index=git(["ls-files", "--stage"], repo).stdout,
        staged_diff=git(["diff", "--cached", "--binary"], repo).stdout,
        worktree_diff=git(["diff", "--binary"], repo).stdout,
        owned_files=_owned_file_bytes(repo),
        operation_markers=_operation_marker_bytes(repo),
    )


def _owned_file_bytes(repo: Path) -> tuple[tuple[str, bytes], ...]:
    rows: list[tuple[str, bytes]] = []
    for root, dirnames, filenames in os.walk(repo):
        root_path = Path(root)
        relative_root = root_path.relative_to(repo)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _ignored_primary_parts((*relative_root.parts, dirname))
        ]
        for filename in filenames:
            path = root_path / filename
            relative = path.relative_to(repo)
            if _ignored_primary_parts(relative.parts):
                continue
            rows.append((relative.as_posix(), path.read_bytes()))
    return tuple(sorted(rows))


def _ignored_primary_parts(parts: tuple[str, ...]) -> bool:
    return bool(parts) and (
        parts[0] == ".git" or (len(parts) >= 2 and parts[:2] == ("sase", "repos"))
    )


def _operation_marker_bytes(repo: Path) -> tuple[tuple[str, bytes | None], ...]:
    marker = repo / ".sase" / "checkout.json"
    return (
        (
            marker.relative_to(repo).as_posix(),
            marker.read_bytes() if marker.exists() else None,
        ),
    )


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


def _chop_runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="sidecar_auto_sync",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
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


class TestLaunchAndArchiveWorkflowsLeavePrimaryUntouched:
    def test_approval_time_plan_archive_writes_leased_checkout_only(
        self, tmp_path: Path
    ) -> None:
        primary, origin = _init_primary(tmp_path)
        checkout = tmp_path / "proj_10"
        clone(origin, checkout)
        project_file = _write_project_file(
            tmp_path / "projects" / "demo" / "demo.sase",
            primary=primary,
        )
        plan = tmp_path / "approved_plan.md"
        plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
        before = _snapshot(primary)

        with (
            patched_operational_lease(checkout, primary_checkout=primary),
            patched_sdd_policy("in_tree"),
            patch("sase.sdd.files.get_yyyymm", return_value="202608"),
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
            patch(
                "sase.file_references.format_with_prettier",
                side_effect=lambda content: content,
            ),
        ):
            archived = archive_approved_plan(
                {"agent_project_file": str(project_file)},
                plan,
                tier="tale",
                push_after_commit=False,
            )

        archived_path = checkout / "sdd" / "plans" / "202608" / "approved_plan.md"
        assert Path(archived) == archived_path
        assert archived_path.is_file()
        assert not (primary / "sdd" / "plans" / "202608" / "approved_plan.md").exists()
        assert _snapshot(primary) == before

    def test_epic_launch_starts_from_leased_checkout_only(self, tmp_path: Path) -> None:
        primary, origin = _init_primary(tmp_path)
        checkout = tmp_path / "proj_10"
        clone(origin, checkout)
        lease = fake_operational_lease(
            checkout,
            project="demo",
            workflow="epic-launch",
            holder="planner",
            primary_checkout=primary,
        )
        plan = tmp_path / "approved_epic.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        monitor = SimpleNamespace(monitor_id="m1")
        before = _snapshot(primary)

        with (
            patch("sase.procs.procs_dir", return_value=tmp_path / "procs"),
            patch("sase.procs.read_procs", return_value=[]),
            patch(
                "sase.workspace_provider.lease.acquire_operational_lease",
                return_value=lease,
            ),
            patch("sase.workspace_provider.lease.release_operational_lease"),
            patch("sase.monitor.start.start_monitor", return_value=monitor) as start,
        ):
            submitted = start_epic_launch_monitor(
                plan,
                project="demo",
                host_action_data={"agent_name": "planner"},
            )

        assert submitted is monitor
        assert start.call_args.args[0].cwd == str(checkout)
        assert _snapshot(primary) == before

    def test_task_launch_submits_from_leased_checkout_only(
        self, tmp_path: Path
    ) -> None:
        primary, origin = _init_primary(tmp_path)
        checkout = tmp_path / "proj_10"
        clone(origin, checkout)
        lease = fake_operational_lease(
            checkout,
            project="demo",
            workflow="task-launch",
            holder="task-launch:sase-42",
            primary_checkout=primary,
        )
        task = SimpleNamespace(task_id="task1")
        before = _snapshot(primary)

        with (
            patch("sase.procs.procs_dir", return_value=tmp_path / "procs"),
            patch("sase.procs.read_procs", return_value=[]),
            patch(
                "sase.workspace_provider.lease.acquire_operational_lease",
                return_value=lease,
            ),
            patch(
                "sase.workspace_provider.lease.submit_via_lease",
                return_value=task,
            ) as submit,
        ):
            submitted = submit_task_launch_task("sase-42", project="demo")

        assert submitted is task
        assert submit.call_args.args[0].cwd == str(checkout)
        assert _snapshot(primary) == before

    @pytest.mark.parametrize("launcher", ["epic", "task"])
    @pytest.mark.parametrize("step", ["allocation", "materialization", "transfer"])
    def test_launch_lease_failures_surface_without_primary_fallback(
        self, tmp_path: Path, launcher: str, step: str
    ) -> None:
        primary, _origin = _init_primary(tmp_path)
        plan = tmp_path / "approved_epic.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        error = OperationalLeaseError(step, f"{step} failed")
        before = _snapshot(primary)

        with (
            patch("sase.procs.procs_dir", return_value=tmp_path / "procs"),
            patch("sase.procs.read_procs", return_value=[]),
            patch(
                "sase.workspace_provider.lease.acquire_operational_lease",
                side_effect=error,
            ),
            patch("sase.monitor.start.start_monitor") as start,
            patch("sase.workspace_provider.lease.submit_via_lease") as submit,
            pytest.raises(OperationalLeaseError, match=step),
        ):
            if launcher == "epic":
                start_epic_launch_monitor(
                    plan,
                    project="demo",
                    host_action_data={"agent_name": "planner"},
                )
            else:
                submit_task_launch_task("sase-42", project="demo")

        start.assert_not_called()
        submit.assert_not_called()
        assert _snapshot(primary) == before


class TestWaiterDrivenSidecarTickLeavesPrimaryUntouched:
    def test_live_bead_waiter_tick_converges_beads_sidecar_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase._sidecar_auto_sync as sidecar_auto_sync
        import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop

        primary, _origin = _init_primary(tmp_path)
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        sidecar_remote = tmp_path / "beads.git"
        seed = tmp_path / "beads-seed"
        sidecar = primary / "sase" / "repos" / "beads"
        init_bare_repo(sidecar_remote)
        clone(sidecar_remote, seed)
        (seed / "README.md").write_text("v1\n", encoding="utf-8")
        commit_all(seed, "v1")
        git(["push", "-u", "origin", "main"], seed)
        clone(sidecar_remote, sidecar)
        before = _snapshot(primary)

        (seed / "README.md").write_text("v2\n", encoding="utf-8")
        commit_all(seed, "v2")
        git(["push"], seed)
        new_head = git(["rev-parse", "HEAD"], seed).stdout.strip()

        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [
                {
                    _SIDECAR_ROLE_KEY: "beads",
                    "auto_sync": False,
                    "disabled": False,
                    _SIDECAR_REMOTE_URL_KEY: str(sidecar_remote),
                }
            ],
        )
        monkeypatch.setattr(
            sidecar_sync_chop,
            "_enabled_project_records",
            lambda: [
                SimpleNamespace(
                    project_name="demo",
                    project_file=str(project_file),
                    workspace_dir=str(primary),
                )
            ],
        )
        monkeypatch.setattr(sidecar_sync_chop, "auto_sync_roles", lambda _primary: ())
        monkeypatch.setattr(
            sidecar_sync_chop, "bead_refresh_mode", lambda: "background"
        )
        monkeypatch.setattr(
            sidecar_sync_chop,
            "_projects_with_live_bead_waits",
            lambda _root: frozenset({"demo"}),
        )
        monkeypatch.setattr(
            sidecar_sync_chop, "pending_sidecar_sync_roles", lambda _project: ()
        )
        mark_hint = MagicMock()
        clear_hint = MagicMock()
        monkeypatch.setattr(sidecar_sync_chop, "mark_sidecar_sync_hint", mark_hint)
        monkeypatch.setattr(sidecar_sync_chop, "clear_sidecar_sync_hint", clear_hint)

        result = sidecar_sync_chop._run(_chop_runtime(tmp_path))

        assert result.counters["targets"] == 1
        assert result.counters["refreshed"] == 1
        mark_hint.assert_called_once_with("demo", "beads")
        clear_hint.assert_called_once_with("demo", "beads")
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == new_head
        assert _snapshot(primary) == before
