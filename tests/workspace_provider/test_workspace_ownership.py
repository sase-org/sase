"""Workspace ownership and mutation-contract coverage (sase-mq.1)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sase.bead.store_locator import (
    canonical_plans_dir_for_project,
    canonical_sidecar_dir_for_project,
)
from sase.running_field import WorkspaceClaim
from sase.sdd.files import commit_sdd_files
from sase.workspace_provider.marker import write_marker
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    WorkspaceOwnershipError,
    authorize_store_mutation,
    leased_operational_context,
    normalize_workspace_num,
    primary_sidecar_sync_context,
    read_only_canonical_context,
    user_directed_context,
    writable_beads_dir,
    writable_checkout_dir,
    writable_plans_dir,
)
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import (
    LEGACY_PRIMARY_WORKSPACE_NUM,
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)
from tests._sdd_commit_helpers import init_test_git_repo


def _adjacent_config() -> dict[str, object]:
    return {"workspace": {"root": "adjacent", "project_key": "demo"}}


def _managed_config(tmp_path: Path) -> dict[str, object]:
    return {
        "workspace": {
            "root": str(tmp_path / "managed-root"),
            "project_key": "demo",
        }
    }


def _write_project_file(
    path: Path,
    *,
    primary: Path,
    claims: list[WorkspaceClaim] | None = None,
) -> Path:
    lines = [
        f"WORKSPACE_DIR: {primary}\n",
        "\n",
    ]
    if claims:
        lines.append("RUNNING:\n")
        for claim in claims:
            lines.append(claim.to_line() + "\n")
    lines.extend(
        [
            "NAME: demo\n",
            "DESCRIPTION:\n",
            "  ownership contract fixture\n",
            "STATUS: Ready\n",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _claim(workspace_num: int, pid: int | None = None) -> WorkspaceClaim:
    return WorkspaceClaim(
        workspace_num,
        "ownership-op",
        None,
        pid=os.getpid() if pid is None else pid,
    )


def _prepare_numbered_checkout(
    store: WorkspaceStore,
    workspace_num: int,
) -> Path:
    workspace_path = store.resolve(workspace_num)
    checkout = Path(workspace_path.checkout_dir.rstrip("/")).resolve()
    checkout.mkdir(parents=True)
    record_workspace(store, workspace_path)
    write_marker(store, workspace_path)
    return checkout


def _init_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


class TestNormalizeWorkspaceNum:
    def test_legacy_one_is_primary(self) -> None:
        assert (
            normalize_workspace_num(LEGACY_PRIMARY_WORKSPACE_NUM)
            == PRIMARY_WORKSPACE_NUM
        )

    def test_zero_and_pool_numbers_are_unchanged(self) -> None:
        assert normalize_workspace_num(0) == 0
        assert normalize_workspace_num(10) == 10


class TestLeasedOperationalContext:
    def test_legacy_primary_number_is_not_leasable(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        with pytest.raises(WorkspaceOwnershipError, match="legacy #1"):
            leased_operational_context(
                "demo",
                1,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[_claim(1)],
                process_running=lambda _pid: True,
            )

    def test_reserved_workspace_is_not_leasable(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        with pytest.raises(WorkspaceOwnershipError, match="reserved workspace"):
            leased_operational_context(
                "demo",
                5,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[_claim(5)],
                process_running=lambda _pid: True,
            )

    def test_adjacent_layout_requires_marker_and_claim(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        checkout = _prepare_numbered_checkout(store, 10)

        context = leased_operational_context(
            "demo",
            10,
            project_file=project_file,
            config=_adjacent_config(),
            env={},
            claims=[_claim(10)],
            process_running=lambda _pid: True,
        )
        assert context.access_kind is AccessKind.LEASED_OPERATIONAL
        assert context.mutation_origin is MutationOrigin.MACHINE
        assert context.workspace_num == 10
        assert context.checkout_dir == checkout
        assert writable_checkout_dir(context) == checkout
        assert writable_beads_dir(context).is_relative_to(checkout)

    def test_managed_root_layout_leases_claimed_checkout(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        config = _managed_config(tmp_path)
        store = WorkspaceStore(str(primary), config=config, env={})
        checkout = _prepare_numbered_checkout(store, 12)
        assert "managed-root" in str(checkout)

        context = leased_operational_context(
            "demo",
            12,
            project_file=project_file,
            config=config,
            env={},
            claims=[_claim(12)],
            process_running=lambda _pid: True,
        )
        assert context.checkout_dir == checkout
        assert writable_plans_dir(context).is_relative_to(checkout)

    def test_missing_marker_fails_closed(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        workspace_path = store.resolve(10)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        record_workspace(store, workspace_path)

        with pytest.raises(WorkspaceOwnershipError, match="no checkout marker"):
            leased_operational_context(
                "demo",
                10,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[_claim(10)],
                process_running=lambda _pid: True,
            )

    def test_missing_claim_fails_closed(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        _prepare_numbered_checkout(store, 10)

        with pytest.raises(WorkspaceOwnershipError, match="no matching live"):
            leased_operational_context(
                "demo",
                10,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[],
                process_running=lambda _pid: True,
            )

    def test_dead_claim_pid_fails_closed(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        _prepare_numbered_checkout(store, 10)

        with pytest.raises(WorkspaceOwnershipError, match="no matching live"):
            leased_operational_context(
                "demo",
                10,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[_claim(10, pid=1)],
                process_running=lambda _pid: False,
            )

    def test_suffix_lookalike_without_registry_is_not_leased(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        lookalike = tmp_path / "proj_10"
        lookalike.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)

        with pytest.raises(WorkspaceOwnershipError, match="no registry entry"):
            leased_operational_context(
                "demo",
                10,
                checkout_dir=lookalike,
                project_file=project_file,
                config=_adjacent_config(),
                env={},
                claims=[_claim(10)],
                process_running=lambda _pid: True,
            )


class TestUserDirectedAndCanonical:
    def test_foreground_user_may_use_primary(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        record_workspace(store, store.resolve(PRIMARY_WORKSPACE_NUM))

        (primary / "src").mkdir()
        context = user_directed_context(
            cwd=primary / "src",
            project="demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )
        assert context.access_kind is AccessKind.USER_DIRECTED
        assert context.workspace_num == PRIMARY_WORKSPACE_NUM
        authorize_store_mutation(
            primary / ".sase" / "sdd",
            mutation_origin="user",
            context=context,
        )

    def test_nested_sidecar_belongs_to_numbered_checkout(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        checkout = _prepare_numbered_checkout(store, 11)
        sidecar = checkout / "sase" / "repos" / "beads"
        sidecar.mkdir(parents=True)

        context = user_directed_context(
            cwd=sidecar,
            project="demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )
        assert context.workspace_num == 11
        assert context.checkout_dir == checkout

    def test_nested_sidecar_under_primary_is_user_owned(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        record_workspace(store, store.resolve(PRIMARY_WORKSPACE_NUM))
        sidecar = primary / "sase" / "repos" / "plans"
        sidecar.mkdir(parents=True)

        context = user_directed_context(
            cwd=sidecar,
            project="demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )
        assert context.workspace_num == PRIMARY_WORKSPACE_NUM
        assert context.checkout_dir == primary.resolve()

    def test_read_only_canonical_rejects_writable_helpers(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        context = read_only_canonical_context(
            "demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )
        with pytest.raises(WorkspaceOwnershipError, match="read-only canonical"):
            writable_checkout_dir(context)
        with pytest.raises(WorkspaceOwnershipError, match="read-only canonical"):
            authorize_store_mutation(
                primary,
                mutation_origin="user",
                context=context,
            )


class TestMachineAuthorization:
    def test_machine_mutation_of_primary_fails(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        (primary / ".sase").mkdir(parents=True)
        (primary / ".sase" / "sdd-store.json").write_text("{}", encoding="utf-8")

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            authorize_store_mutation(
                primary / ".sase" / "sdd",
                mutation_origin="machine",
            )

    def test_machine_mutation_without_marker_fails_closed(self, tmp_path: Path) -> None:
        orphan = tmp_path / "unmarked"
        orphan.mkdir()
        with pytest.raises(WorkspaceOwnershipError, match="missing checkout marker"):
            authorize_store_mutation(orphan, mutation_origin="machine")

    def test_machine_mutation_of_claimed_checkout_is_allowed(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        checkout = _prepare_numbered_checkout(store, 10)
        context = leased_operational_context(
            "demo",
            10,
            project_file=project_file,
            config=_adjacent_config(),
            env={},
            claims=[_claim(10)],
            process_running=lambda _pid: True,
        )
        authorize_store_mutation(
            checkout / ".sase" / "sdd",
            mutation_origin="machine",
            context=context,
        )

    def test_sidecar_sync_cannot_mutate_primary_repo(self, tmp_path: Path) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        context = primary_sidecar_sync_context(
            "demo",
            "plans",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )
        with pytest.raises(WorkspaceOwnershipError, match="primary checkout"):
            writable_checkout_dir(context)
        sidecar = primary / "sase" / "repos" / "plans"
        sidecar.mkdir(parents=True)
        _init_git(primary)
        _init_git(sidecar)
        authorize_store_mutation(
            sidecar,
            mutation_origin="machine",
            context=context,
        )
        with pytest.raises(WorkspaceOwnershipError, match="may only mutate"):
            authorize_store_mutation(
                primary,
                mutation_origin="machine",
                context=context,
            )


class TestCanonicalLocators:
    def test_canonical_plans_and_sidecar_are_read_only_primary_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "sase-home"
        project_dir = home / "projects" / "demo"
        primary = tmp_path / "proj"
        plans = primary / ".sase" / "sdd" / "plans"
        research = primary / ".sase" / "sdd" / "research"
        plans.mkdir(parents=True)
        research.mkdir(parents=True)
        _write_project_file(project_dir / "demo.sase", primary=primary)
        monkeypatch.setenv("SASE_HOME", str(home))

        assert canonical_plans_dir_for_project("demo") == plans
        assert canonical_sidecar_dir_for_project("demo", "research") == research


class TestCommitSeam:
    def test_user_origin_still_commits_unmanaged_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "scratch"
        init_test_git_repo(repo)
        (repo / "note.md").write_text("hello", encoding="utf-8")
        assert commit_sdd_files(repo, "user scratch")
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "user scratch" in log.stdout

    def test_machine_origin_refuses_primary_before_staging(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "proj"
        store_dir = primary / ".sase" / "sdd"
        _init_git(store_dir)
        (primary / ".sase" / "sdd-store.json").write_text("{}", encoding="utf-8")
        dirty = store_dir / "note.md"
        dirty.write_text("secret", encoding="utf-8")

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            commit_sdd_files(
                store_dir,
                "machine must not touch primary",
                mutation_origin="machine",
            )

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=store_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "note.md" in status.stdout
        log = subprocess.run(
            ["git", "log", "-1"],
            cwd=store_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert log.returncode != 0

    def test_machine_origin_commits_inside_leased_checkout(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        store = WorkspaceStore(str(primary), config=_adjacent_config(), env={})
        checkout = _prepare_numbered_checkout(store, 10)
        repo = checkout / ".sase" / "sdd"
        _init_git(repo)
        (repo / "note.md").write_text("leased", encoding="utf-8")
        context = leased_operational_context(
            "demo",
            10,
            project_file=project_file,
            config=_adjacent_config(),
            env={},
            claims=[_claim(10)],
            process_running=lambda _pid: True,
        )

        assert commit_sdd_files(
            repo,
            "machine lease write",
            mutation_origin="machine",
            operation_context=context,
        )
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "machine lease write" in log.stdout
