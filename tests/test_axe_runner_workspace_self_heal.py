"""Self-healing checkout preparation for numbered workspaces (sase-16e.2).

``prepare_workspace(..., self_heal=True)`` runs an opt-in heal ladder for
numbered ephemeral workspaces: rescue leftover state outside the workspace,
abort in-progress git operations, survive stash failures, replace a
conflicting sync rebase with rescue plus a hard reset to the default branch,
and verify a clean postcondition. ``self_heal=False`` (the default, kept by
``sase workspace open``) preserves today's fail-closed behavior.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.axe.runner_workspace import WorkspacePreparationError, prepare_workspace
from sase.vcs_provider import VCS_DEFAULT_REVISION


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


def _init_origin(path: Path) -> None:
    path.mkdir(parents=True)
    _git_no_check(path, "init", "-q", "-b", "main", str(path))
    _configure(path)
    (path / "README.md").write_text("origin v1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    (path / "other.txt").write_text("other v1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "second")


def _clone(origin: Path, target: Path) -> Path:
    _git_no_check(target.parent, "clone", "-q", str(origin), str(target))
    _configure(target)
    return target


def _head(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def _porcelain(repo: Path) -> str:
    return _git(repo, "status", "--porcelain").stdout.strip()


def _git_dir(repo: Path) -> Path:
    raw = _git(repo, "rev-parse", "--git-dir").stdout.strip()
    git_dir = Path(raw)
    return git_dir if git_dir.is_absolute() else repo / git_dir


def _advance_origin(origin: Path, content: str) -> None:
    (origin / "README.md").write_text(content, encoding="utf-8")
    _git(origin, "commit", "-aq", "-m", "advance")


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


def _bundle_shas(bundle: Path) -> str:
    return subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _entry_holds_sha(entries: list[Path], sha: str) -> bool:
    for entry in entries:
        bundle = entry / "local-commits.bundle"
        if bundle.is_file() and sha in _bundle_shas(bundle):
            return True
    return False


def _prepare(repo: Path) -> None:
    prepare_workspace(
        str(repo),
        "heal-cl",
        VCS_DEFAULT_REVISION,
        workspace_num=7,
        self_heal=True,
    )


def test_self_heal_repairs_mid_rebase_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A conflicted mid-rebase checkout ends clean at origin/main, rescued."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "local divergent change")
    local_sha = _head(checkout)
    _git(checkout, "fetch", "-q", "origin")
    result = _git_no_check(checkout, "rebase", "origin/main")
    assert result.returncode != 0
    git_dir = _git_dir(checkout)
    assert (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()

    _prepare(checkout)

    out = capsys.readouterr().out
    assert "Aborted stale rebase" in out
    assert _head(checkout) == _head(checkout, "origin/main")
    assert _git(checkout, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert _porcelain(checkout) == ""
    entries = _rescue_entries(home)
    assert entries, "expected a rescue entry for the conflicted rebase"
    assert _entry_holds_sha(entries, local_sha)


def test_self_heal_repairs_stash_pop_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unmerged paths with no marker still heal via rescue plus reset/clean."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _conflicting_side_setup(checkout)
    assert _git_no_check(checkout, "merge", "side").returncode != 0
    # A stash-pop conflict leaves unmerged paths with no operation marker.
    (_git_dir(checkout) / "MERGE_HEAD").unlink()
    assert _git(checkout, "diff", "--name-only", "--diff-filter=U").stdout.strip()
    expected = _head(checkout)

    _prepare(checkout)

    assert _head(checkout) == expected
    assert _porcelain(checkout) == ""
    assert not (_git_dir(checkout) / "MERGE_HEAD").exists()
    entries = _rescue_entries(home)
    assert entries, "expected a rescue entry for the unmerged worktree"
    assert any((entry / "worktree.patch").is_file() for entry in entries)


def test_self_heal_clears_stale_rebase_marker_without_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale rebase-merge dir with a clean tree heals with no rescue entry."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    (_git_dir(checkout) / "rebase-merge").mkdir()

    _prepare(checkout)

    out = capsys.readouterr().out
    assert "Aborted stale rebase" in out
    assert not (_git_dir(checkout) / "rebase-merge").exists()
    assert _head(checkout) == _head(checkout, "origin/main")
    assert _porcelain(checkout) == ""
    assert _rescue_entries(home) == []


def _conflicting_side_setup(checkout: Path) -> None:
    """Commit conflicting changes on main and a side branch (origin untouched)."""
    _git(checkout, "checkout", "-qb", "side")
    (checkout / "README.md").write_text("side v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "side change")
    _git(checkout, "checkout", "-q", "main")
    (checkout / "README.md").write_text("main v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "main change")


@pytest.mark.parametrize("operation", ["merge", "cherry-pick", "revert", "am"])
def test_self_heal_aborts_in_progress_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
) -> None:
    """Merge/cherry-pick/revert/am states abort; the branch tip is preserved."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    if operation == "merge":
        _conflicting_side_setup(checkout)
        assert _git_no_check(checkout, "merge", "side").returncode != 0
    elif operation == "cherry-pick":
        _conflicting_side_setup(checkout)
        side_sha = _head(checkout, "side")
        assert _git_no_check(checkout, "cherry-pick", side_sha).returncode != 0
    elif operation == "revert":
        (checkout / "README.md").write_text("revert me\n", encoding="utf-8")
        _git(checkout, "commit", "-aq", "-m", "revert target")
        (checkout / "README.md").write_text("later change\n", encoding="utf-8")
        _git(checkout, "commit", "-aq", "-m", "later change")
        target = _git(checkout, "rev-parse", "HEAD~1").stdout.strip()
        assert _git_no_check(checkout, "revert", target).returncode != 0
    else:  # am
        _conflicting_side_setup(checkout)
        patch = tmp_path / "side.patch"
        patch.write_text(
            _git(checkout, "format-patch", "-1", "--stdout", "side").stdout,
            encoding="utf-8",
        )
        assert _git_no_check(checkout, "am", str(patch)).returncode != 0
    # Conflicting operations never move the branch tip; healing must preserve it.
    expected = _head(checkout)

    _prepare(checkout)

    out = capsys.readouterr().out
    assert "Aborted stale" in out
    git_dir = _git_dir(checkout)
    for marker in (
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "sequencer",
    ):
        assert not (git_dir / marker).exists(), marker
    assert _porcelain(checkout) == ""
    assert _git(checkout, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert _head(checkout) == expected
    assert _rescue_entries(home), "mid-operation state must be rescued first"


def test_self_heal_aborts_bisect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An in-progress bisect resets; the branch tip is preserved."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    expected = _head(checkout)
    older = _git(checkout, "rev-parse", "HEAD~1").stdout.strip()
    _git(checkout, "bisect", "start")
    _git(checkout, "bisect", "bad")
    _git(checkout, "bisect", "good", older)
    assert (_git_dir(checkout) / "BISECT_LOG").exists()

    _prepare(checkout)

    git_dir = _git_dir(checkout)
    assert not (git_dir / "BISECT_LOG").exists()
    assert not (git_dir / "BISECT_EXPECTED_REV").exists()
    assert _git(checkout, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert _head(checkout) == expected
    assert _porcelain(checkout) == ""


def test_self_heal_resets_conflicting_divergence_with_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A conflicting local default branch resets to origin after rescue."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "local divergent change")
    local_sha = _head(checkout)
    _git(checkout, "fetch", "-q", "origin")

    _prepare(checkout)

    out = capsys.readouterr().out
    assert "rescued to" in out
    assert _head(checkout) == _head(checkout, "origin/main")
    assert _porcelain(checkout) == ""
    entries = _rescue_entries(home)
    assert _entry_holds_sha(entries, local_sha)
    recovery = _git(
        checkout, "for-each-ref", "--format=%(refname)", "refs/sase/recovery"
    ).stdout.strip()
    assert recovery, "expected an in-clone recovery ref for the reset-away commits"


def test_self_heal_rescues_detached_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detached HEAD holding an orphan commit is rescued, then re-attached."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _git(checkout, "checkout", "-q", "--detach", "HEAD")
    (checkout / "orphan.txt").write_text("orphan\n", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-q", "-m", "orphan commit")
    orphan_sha = _head(checkout)

    _prepare(checkout)

    assert _git(checkout, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert _head(checkout) == _head(checkout, "origin/main")
    assert _porcelain(checkout) == ""
    assert _entry_holds_sha(_rescue_entries(home), orphan_sha)
    assert (
        _git(
            checkout, "for-each-ref", "--format=%(refname)", "refs/sase/rescue-tmp"
        ).stdout.strip()
        == ""
    ), "rescue temp refs must be cleaned up"


def test_self_heal_carries_clean_rebase_without_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-conflicting divergence still rebases; no rescue entry is filed."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _advance_origin(origin, "origin v2\n")
    (checkout / "other.txt").write_text("local other\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "local non-conflicting change")
    _git(checkout, "fetch", "-q", "origin")

    _prepare(checkout)

    log = _git(checkout, "log", "--oneline").stdout
    assert "local non-conflicting change" in log
    assert "advance" in log
    assert _porcelain(checkout) == ""
    assert _rescue_entries(home) == []


def test_self_heal_stashes_plain_dirty_worktree_without_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain dirty worktree keeps its stash backup and files no rescue."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    (checkout / "README.md").write_text("dirty edit\n", encoding="utf-8")

    _prepare(checkout)

    assert _porcelain(checkout) == ""
    assert _git(checkout, "stash", "list").stdout.strip(), "expected a stash entry"
    assert _rescue_entries(home) == []


def test_self_heal_false_keeps_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without self-heal, a wedged checkout still fails closed (no rescue)."""
    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "local divergent change")
    _git(checkout, "fetch", "-q", "origin")
    assert _git_no_check(checkout, "rebase", "origin/main").returncode != 0

    with pytest.raises(WorkspacePreparationError) as exc_info:
        prepare_workspace(str(checkout), "heal-cl", VCS_DEFAULT_REVISION)

    assert exc_info.value.reclone_eligible is False
    assert _rescue_entries(home) == []


def test_self_heal_fetch_failure_is_hard_and_ineligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing fetch stays a hard failure with its own step (never recloned)."""
    _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    with pytest.raises(WorkspacePreparationError) as exc_info:
        _prepare(checkout)

    assert exc_info.value.step == "fetch"
    assert exc_info.value.reclone_eligible is False


def test_self_heal_skipped_for_non_git_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Providers without heal operations keep today's fail-closed behavior."""
    from unittest.mock import MagicMock

    home, _ = _redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    _init_origin(origin)
    checkout = _clone(origin, tmp_path / "ws7")
    _advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    _git(checkout, "commit", "-aq", "-m", "local divergent change")
    _git(checkout, "fetch", "-q", "origin")
    assert _git_no_check(checkout, "rebase", "origin/main").returncode != 0

    provider = MagicMock()
    provider.get_default_parent_revision.return_value = "origin/main"
    provider.checkout.return_value = (True, None)
    provider.sync_workspace.return_value = (True, None)
    provider.stash_and_clean.return_value = (
        False,
        "git stash push failed: cannot stash unmerged changes",
    )
    for heal_op in (
        "inspect_checkout",
        "abort_in_progress_operations",
        "force_checkout",
        "recreate_branch_from_remote",
        "fetch_origin",
        "rebase_onto",
        "reset_to_remote",
        "in_progress_operations",
    ):
        getattr(provider, heal_op).side_effect = NotImplementedError(
            f"{heal_op} is not supported by this VCS provider"
        )
    monkeypatch.setattr(
        "sase.axe.runner_workspace_prepare.get_vcs_provider", lambda cwd: provider
    )
    monkeypatch.setattr(
        "sase.workflows.commit_utils.workspace.get_vcs_provider",
        lambda cwd: provider,
    )

    with pytest.raises(WorkspacePreparationError) as exc_info:
        _prepare(checkout)

    assert exc_info.value.step == "clean"
    assert exc_info.value.reclone_eligible is False
    assert _rescue_entries(home) == []
