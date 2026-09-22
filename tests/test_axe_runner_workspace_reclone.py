"""Last-resort workspace re-creation and non-holding setup failures (sase-16e.3).

When in-place healing still fails, the numbered checkout is rescued and
re-materialized from the primary checkout, entered once more, and prepared
once more (launch, retry, and linked-repo paths). Workspaces whose setup
ultimately failed are released rather than held.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_runner_setup import (
    enter_agent_workspace,
    prepare_linked_repo_workspaces_if_needed,
    prepare_workspace_if_needed,
)
from sase.axe.runner_workspace import (
    WorkspacePreparationError,
    prepare_launch_workspace_repos,
)
from sase.linked_repos import LinkedRepoResolution, _ResolvedLinkedRepo
from sase.llm_provider.retry_config import ProviderRetryConfig
from sase.running_field import WorkspaceClaim
from sase.vcs_provider import VCS_DEFAULT_REVISION
from sase.workspace_provider import _utils_checkout as utils_checkout
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record
from sase.workspace_provider.utils import recreate_managed_workspace
from tests._axe_run_agent_exec_retry_helpers import (
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
    make_ctx_with_update_target,
    make_state,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _git_no_check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=False, capture_output=True, text=True
    )


def _configure(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


def _project_file_with_claim(tmp_path: Path, claim: WorkspaceClaim) -> str:
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\nRUNNING:\n")
        f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
        return f.name


def _claim_checkout_num7(
    tmp_path: Path, workspace_dir: Path, workflow: str = "ace(run)-mine"
) -> str:
    """Claim workspace #7 for this process (guard + occupant record)."""
    project_file = _project_file_with_claim(
        tmp_path,
        WorkspaceClaim(
            workspace_num=7,
            workflow=workflow,
            cl_name="feature",
            pid=os.getpid(),
            artifacts_timestamp="mine-ts",
        ),
    )
    write_occupant_record(
        str(workspace_dir),
        new_occupant_record(
            pid=os.getpid(),
            workflow=workflow,
            project="sase",
            workspace_num=7,
        ),
    )
    return project_file


def _redirect_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    """Point SASE_HOME and rescue notifications at tmp; return home and notes."""
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )
    return home, notified


def _rescue_entries(home: Path) -> list[Path]:
    return sorted(path.parent for path in home.rglob("manifest.json"))


def _eligible_error(workspace_dir: str) -> WorkspacePreparationError:
    return WorkspacePreparationError(
        "self-heal postcondition failed: worktree is still dirty",
        step="verify",
        workspace_dir=workspace_dir,
        reclone_eligible=True,
    )


def _ineligible_fetch_error(workspace_dir: str) -> WorkspacePreparationError:
    return WorkspacePreparationError(
        "git fetch origin failed: exit 128: remote hung up unexpectedly",
        step="fetch",
        workspace_dir=workspace_dir,
        reclone_eligible=False,
    )


class TestRecreateRefusesPrimary:
    @pytest.mark.parametrize("workspace_num", [0, 1])
    def test_primary_checkout_is_never_recreated(
        self, tmp_path: Path, workspace_num: int
    ) -> None:
        primary = tmp_path / "primary"
        primary.mkdir()
        with pytest.raises(RuntimeError, match="numbered workspaces only"):
            recreate_managed_workspace(str(primary), workspace_num)
        assert list(tmp_path.iterdir()) == [primary]


class TestPrepareWorkspaceIfNeededReclone:
    def test_eligible_failure_recreates_and_prepares_again(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        project_file = _claim_checkout_num7(tmp_path, workspace_dir)
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "sase.axe.run_agent_runner_setup.prepare_workspace",
                side_effect=[_eligible_error(str(workspace_dir)), None],
            ) as prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value=str(workspace_dir),
            ) as recreate,
            patch("sase.sdd.store.ensure_workspace_sdd_clone"),
            patch("sase.linked_repos.clear_workspace_repos"),
        ):
            prepare_workspace_if_needed(
                workspace_dir=str(workspace_dir),
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                project_file=project_file,
                workflow_name="ace(run)-mine",
                artifacts_timestamp="mine-ts",
                is_home_mode=False,
                retry_handoff=None,
            )

        assert prepare.call_count == 2
        recreate.assert_called_once_with(
            str(workspace_dir), 7, project_file=project_file
        )
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_dir)
        out = capsys.readouterr().out
        assert "could not be repaired in place" in out
        assert "re-creating it from the primary checkout" in out

    def test_ineligible_fetch_failure_skips_recreation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup.prepare_workspace",
                side_effect=[_ineligible_fetch_error("/tmp/workspace")],
            ),
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
            ) as recreate,
            pytest.raises(RuntimeError, match="remote hung up unexpectedly"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        recreate.assert_not_called()
        assert "could not be repaired in place" not in capsys.readouterr().out

    def test_primary_checkout_never_recreates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup.prepare_workspace",
                side_effect=[_eligible_error("/tmp/workspace")],
            ),
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
            ) as recreate,
            pytest.raises(RuntimeError, match="Failed to prepare workspace"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=1,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        recreate.assert_not_called()

    def test_second_failure_fails_the_launch(self, tmp_path: Path) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup.prepare_workspace",
                side_effect=[
                    _eligible_error("/tmp/workspace"),
                    _eligible_error("/tmp/workspace"),
                ],
            ) as prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value="/tmp/workspace",
            ) as recreate,
            patch(
                "sase.axe.run_agent_runner_setup.enter_agent_workspace",
            ),
            pytest.raises(RuntimeError, match="Failed to prepare workspace"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        assert prepare.call_count == 2
        recreate.assert_called_once()


class TestRetryPrepareWorkspaceReclone:
    def _retry_cfg(self) -> ProviderRetryConfig:
        return ProviderRetryConfig(
            max_retries=2,
            error_patterns=["rate limit"],
            wait_times=[0],
        )

    def test_retry_reprep_recreates_on_eligible_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        project_file = _claim_checkout_num7(tmp_path, workspace_dir)
        monkeypatch.chdir(tmp_path)
        ctx = dataclasses.replace(
            make_ctx_with_update_target(tmp_path),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            project_file=project_file,
            workflow_name="ace(run)-mine",
        )
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=self._retry_cfg())

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                side_effect=[_eligible_error(str(workspace_dir)), None],
            ) as mock_prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value=str(workspace_dir),
            ) as recreate,
        ):
            action = handle_workflow_error(
                RuntimeError("hit a rate limit"), tracker, ctx, state
            )

        assert action == "continue"
        assert mock_prepare.call_count == 2
        recreate.assert_called_once_with(
            str(workspace_dir), 7, project_file=project_file
        )
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_dir)


class TestLinkedRepoPrepareReclone:
    def test_linked_clone_recreates_on_eligible_failure(self, tmp_path: Path) -> None:
        primary_dir = tmp_path / "primary"
        primary_dir.mkdir()
        linked_dir = tmp_path / "linked"
        linked_dir.mkdir()
        project_file = _project_file_with_claim(
            tmp_path,
            WorkspaceClaim(
                workspace_num=7,
                workflow="ace(run)-mine",
                cl_name="feature",
                pid=os.getpid(),
                artifacts_timestamp="mine-ts",
            ),
        )
        write_occupant_record(
            str(primary_dir),
            new_occupant_record(
                pid=os.getpid(),
                workflow="ace(run)-mine",
                project="sase",
                workspace_num=7,
            ),
        )
        resolution = LinkedRepoResolution(
            repos=(
                _ResolvedLinkedRepo(
                    name="docs",
                    env_name="DOCS",
                    primary_dir=str(tmp_path / "docs-primary"),
                    workspace_dir=str(linked_dir),
                    workspace_num=7,
                    auto_clone=True,
                ),
            )
        )

        env_before = set(os.environ)
        try:
            with (
                patch(
                    "sase.linked_repos.materialize_linked_repo_workspace",
                    return_value=str(linked_dir),
                ) as materialize,
                patch(
                    "sase.axe.run_agent_runner_setup.prepare_workspace",
                    side_effect=[_eligible_error(str(linked_dir)), None],
                ) as prepare,
            ):
                prepare_linked_repo_workspaces_if_needed(
                    resolution=resolution,
                    cl_name="feature",
                    primary_workspace_dir=str(primary_dir),
                    workspace_num=7,
                    project_name="sase",
                    project_file=project_file,
                    workflow_name="ace(run)-mine",
                    artifacts_timestamp="mine-ts",
                )
        finally:
            for key in set(os.environ) - env_before:
                del os.environ[key]

        assert materialize.call_count == 2
        assert prepare.call_count == 2


def _init_origin(path: Path) -> None:
    path.mkdir(parents=True)
    _git_no_check(path, "init", "-q", "-b", "main", str(path))
    _configure(path)
    (path / "README.md").write_text("origin v1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")


def _clone(origin: Path, target: Path) -> Path:
    _git_no_check(target.parent, "clone", "-q", str(origin), str(target))
    _configure(target)
    return target


def _head(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def _bundle_shas(bundle: Path) -> str:
    return subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _seed_unpublishable_sidecar(
    tmp_path: Path, workspace: Path
) -> tuple[Path, str, Path]:
    """Seed a sidecar clone ahead of its upstream with a failing push remote.

    The clone counts exactly one unpushed commit, and publication fails fast
    against a nonexistent local path, so eviction-mode protection takes the
    rescue-bundle path (a remote-less clone would take the quarantine path).
    Returns the clone, the unpublished commit SHA, and the sidecar origin
    (a fresh clone of which holds the bundle's prerequisite history).
    """
    origin = tmp_path / "sidecar-origin"
    _init_origin(origin)
    sidecar = workspace / "sase" / "repos" / "plans"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    _clone(origin, sidecar)
    (sidecar / "note.md").write_text("unpublished\n", encoding="utf-8")
    _git(sidecar, "add", ".")
    _git(sidecar, "commit", "-q", "-m", "unpublished sidecar commit")
    sha = _head(sidecar)
    _git(sidecar, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    return sidecar, sha, origin


_REAL_ENSURE_WORKSPACE_CHECKOUT = utils_checkout.ensure_workspace_checkout


def _adjacent_ensure(primary: str, workspace_num: int, **kwargs: object) -> str:
    """Run the real checkout materialization under the adjacent root policy.

    Overrides unconditionally: callers pass explicit ``None``s that
    ``setdefault`` would keep, which would load the real user config and
    materialize outside tmp.
    """
    kwargs["config"] = {"workspace": {"root": "adjacent"}}
    kwargs["env"] = {}
    return _REAL_ENSURE_WORKSPACE_CHECKOUT(primary, workspace_num, **kwargs)


class TestRecreateManagedWorkspaceRealGit:
    def test_recreates_checkout_and_rescues_branches_stash_and_sidecar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, notified = _redirect_state(tmp_path, monkeypatch)
        origin = tmp_path / "origin"
        _init_origin(origin)
        primary = _clone(origin, tmp_path / "primary")
        workspace = _clone(primary, tmp_path / "primary_7")

        _git(workspace, "checkout", "-qb", "old-work")
        (workspace / "old.txt").write_text("old work\n", encoding="utf-8")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-q", "-m", "old work")
        old_branch_sha = _head(workspace)
        _git(workspace, "checkout", "-q", "main")
        (workspace / "README.md").write_text("stashed change\n", encoding="utf-8")
        _git(workspace, "stash", "push", "-q", "-m", "doomed stash")
        stash_sha = _head(workspace, "stash@{0}")

        _, sidecar_sha, sidecar_origin = _seed_unpublishable_sidecar(
            tmp_path, workspace
        )

        primary_head = _head(primary)

        result = recreate_managed_workspace(
            str(workspace),
            7,
            config={"workspace": {"root": "adjacent"}},
            env={},
        )

        assert result.rstrip("/") == str(workspace)
        assert _head(workspace) == primary_head
        assert _git(workspace, "status", "--porcelain").stdout.strip() == ""
        assert _git(workspace, "branch", "--list", "old-work").stdout.strip() == ""
        assert (
            _git_no_check(workspace, "rev-parse", "--verify", "refs/stash").returncode
            != 0
        )

        entries = _rescue_entries(home)
        assert len(entries) == 2
        assert len(notified) == len(entries)

        checkout_bundle = next(
            entry / "local-commits.bundle"
            for entry in entries
            if (entry / "local-commits.bundle").exists()
            and old_branch_sha in _bundle_shas(entry / "local-commits.bundle")
        )
        assert stash_sha in _bundle_shas(checkout_bundle)
        plans_bundle = next(
            entry / "local-commits.bundle"
            for entry in entries
            if (entry / "local-commits.bundle").exists()
            and sidecar_sha in _bundle_shas(entry / "local-commits.bundle")
        )
        assert plans_bundle != checkout_bundle
        # Every bundle restores: the bundles prune history reachable from
        # remotes, so `git bundle verify` cannot pass on them by design.
        # Fetching into the fresh checkout (which holds the prerequisite
        # history) resolves every rescued SHA, using the manifest's own
        # restore shape.
        _git(
            workspace,
            "fetch",
            str(checkout_bundle),
            "refs/*:refs/sase/rescued-checkout/*",
        )
        for sha in (old_branch_sha, stash_sha):
            _git(workspace, "cat-file", "-e", sha)
        # The sidecar bundle restores into its own lineage: a fresh clone of
        # the sidecar origin holds the prerequisite history the pruned bundle
        # needs.
        restored_sidecar = _clone(sidecar_origin, tmp_path / "restored-plans")
        _git(
            restored_sidecar,
            "fetch",
            str(plans_bundle),
            "refs/*:refs/sase/rescued-plans/*",
        )
        _git(restored_sidecar, "cat-file", "-e", sidecar_sha)


class TestCorruptCheckoutPath:
    def test_corrupt_checkout_rescues_sidecars_before_replacing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.utils import ensure_git_clone_at

        home, _notified = _redirect_state(tmp_path, monkeypatch)
        origin = tmp_path / "origin"
        _init_origin(origin)
        primary = _clone(origin, tmp_path / "primary")
        target = _clone(primary, tmp_path / "primary_7")

        _, sidecar_sha, _ = _seed_unpublishable_sidecar(tmp_path, target)

        # Corrupt the index (not HEAD): `git status` fails, but the checkout
        # is still recognizable enough to pass the object-borrower refusal,
        # which the plan keeps as-is for corruptions it cannot classify.
        (target / ".git" / "index").write_bytes(b"\x00corrupt")
        assert _git_no_check(target, "status").returncode != 0, (
            "test precondition: git status must fail on the corrupted checkout"
        )

        ensure_git_clone_at(str(primary), 7, str(target))

        assert _head(target) == _head(primary)
        entries = _rescue_entries(home)
        assert entries, "the doomed sidecar clone must be rescued before deletion"
        assert any(
            sidecar_sha in _bundle_shas(entry / "local-commits.bundle")
            for entry in entries
            if (entry / "local-commits.bundle").exists()
        )


class TestRecreateEndToEnd:
    """A heal that still fails leads to re-creation; then prep succeeds."""

    def test_forced_verify_failure_recreates_then_launch_prep_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, notified = _redirect_state(tmp_path, monkeypatch)
        origin = tmp_path / "origin"
        _init_origin(origin)
        primary = _clone(origin, tmp_path / "primary")
        workspace = _clone(primary, tmp_path / "primary_7")
        enter_agent_workspace(str(workspace), 7)

        _git(workspace, "checkout", "-qb", "old-work")
        (workspace / "old.txt").write_text("old work\n", encoding="utf-8")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-q", "-m", "old work")
        old_branch_sha = _head(workspace)
        _git(workspace, "checkout", "-q", "main")
        (workspace / "README.md").write_text("stashed change\n", encoding="utf-8")
        _git(workspace, "stash", "push", "-q", "-m", "doomed stash")
        stash_sha = _head(workspace, "stash@{0}")

        _, sidecar_sha, _ = _seed_unpublishable_sidecar(tmp_path, workspace)

        project_file = _claim_checkout_num7(tmp_path, workspace)
        session_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            forced = WorkspacePreparationError(
                "self-heal postcondition failed: forced for re-creation",
                step="verify",
                workspace_dir=str(workspace),
                reclone_eligible=True,
            )
            with (
                patch(
                    "sase.axe.runner_workspace_prepare._verify_healed_checkout",
                    side_effect=[forced, None],
                ),
                patch(
                    "sase.workspace_provider._utils_checkout.ensure_workspace_checkout",
                    side_effect=_adjacent_ensure,
                ),
                patch("sase.sdd.store.ensure_workspace_sdd_clone"),
                patch("sase.sdd.store.auto_connect_sdd_store", return_value=False),
            ):
                fresh_sidecars = prepare_workspace_if_needed(
                    workspace_dir=str(workspace),
                    workspace_num=7,
                    cl_name="feature",
                    update_target=VCS_DEFAULT_REVISION,
                    project_name="sase",
                    project_file=project_file,
                    workflow_name="ace(run)-mine",
                    artifacts_timestamp="mine-ts",
                    is_home_mode=False,
                    retry_handoff=None,
                )
                prepare_launch_workspace_repos(str(workspace), 7)

            assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace)
            assert _head(workspace) == _head(primary)
            assert _git(workspace, "status", "--porcelain").stdout.strip() == ""
            assert isinstance(fresh_sidecars, frozenset)

            entries = _rescue_entries(home)
            assert len(entries) == 2
            assert len(notified) == len(entries)
            assert any(
                old_branch_sha in _bundle_shas(entry / "local-commits.bundle")
                and stash_sha in _bundle_shas(entry / "local-commits.bundle")
                for entry in entries
                if (entry / "local-commits.bundle").exists()
            )
            assert any(
                sidecar_sha in _bundle_shas(entry / "local-commits.bundle")
                for entry in entries
                if (entry / "local-commits.bundle").exists()
            )
        finally:
            os.chdir(session_cwd)
