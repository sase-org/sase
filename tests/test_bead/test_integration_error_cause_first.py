"""Cause-first integration errors and replay sandbox guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd._repository_integration_repair import _cause_first_integration_error


def test_bead_collision_keeps_collision_label() -> None:
    error = _cause_first_integration_error(
        "git rebase failed: Rebasing (1/1)\n"
        "error: could not apply 35f5186 chore(beads): checkpoint approved epic graph\n"
        "hint: Resolve all conflicts manually\n",
        "semantic conflict resolution failed: validation: "
        "duplicate issue_created event for bob-cli-ra",
    )
    assert error.startswith(
        "bead-ID collision with concurrently published history could not be merged:"
    )
    assert "duplicate issue_created event for bob-cli-ra" in error
    assert "hint:" not in error
    assert "Rebasing (1/1)" not in error


def test_duplicate_bead_keeps_collision_label() -> None:
    error = _cause_first_integration_error(
        "git rebase failed",
        "duplicate bead event stream: beads-12",
    )
    assert error.startswith(
        "bead-ID collision with concurrently published history could not be merged:"
    )


def test_non_bead_conflicts_use_neutral_label() -> None:
    error = _cause_first_integration_error(
        "git rebase failed: Rebasing (2/7)\n"
        "hint: Resolve all conflicts manually\n"
        "Could not apply 35f5186 chore(beads): checkpoint",
        "non-bead conflicts remain: 202611/x.md",
    )
    assert error.startswith(
        "conflict with concurrently published history could not be merged:"
    )
    assert "bead-ID collision" not in error
    assert "non-bead conflicts remain: 202611/x.md" in error
    assert "hint:" not in error
    assert "Rebasing (2/7)" not in error


def test_exception_detail_without_duplicate_uses_neutral_label() -> None:
    error = _cause_first_integration_error(
        "git rebase failed",
        "semantic conflict resolution failed: boom",
    )
    assert error.startswith(
        "conflict with concurrently published history could not be merged:"
    )
    assert "bead-ID collision" not in error
    assert "semantic conflict resolution failed: boom" in error


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_replay_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    return remote


def test_publication_conflict_replay_refuses_unsandboxed_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sandbox guard refuses the reset before any recovery ref or reset."""
    from tests.test_bead.sync_test_helpers import configure_git_identity

    from sase.bead._cli_work_from_plan_replay import replay_publication_conflict
    from sase.bead.epic_from_plan import EpicFromPlanError

    remote = _init_replay_remote(tmp_path, "sandbox-beads")
    clone = tmp_path / "sandbox-clone"
    _git(tmp_path, "clone", str(remote), str(clone))
    configure_git_identity(clone)
    (clone / "base.txt").write_text("base\n", encoding="utf-8")
    _git(clone, "add", "base.txt")
    _git(clone, "commit", "-m", "base")
    _git(clone, "push", "-u", "origin", "main")
    launch_base = _git(clone, "rev-parse", "HEAD").stdout.strip()
    (clone / "attempt.txt").write_text("attempt\n", encoding="utf-8")
    _git(clone, "add", "attempt.txt")
    _git(clone, "commit", "-m", "attempt checkpoint")
    attempt_head = _git(clone, "rev-parse", "HEAD").stdout.strip()

    def _refuse(_beads_dir: Path, *, operation: str) -> None:
        raise RuntimeError(f"sandboxed test refusal for {operation}")

    monkeypatch.setattr(
        "sase.core.state_write_guard.assert_bead_store_write_sandboxed",
        _refuse,
    )

    with pytest.raises(EpicFromPlanError, match="NOT discarded") as excinfo:
        replay_publication_conflict(
            beads_dir=clone,
            launch_base=launch_base,
            epic_id="beads-9",
            checkpoint_sha=attempt_head,
            attempt_tip_sha=attempt_head,
            cause="epic graph publication conflicted and could not be merged",
            archived_path=tmp_path / "rollout.md",
        )

    message = str(excinfo.value)
    assert "the bead-store write sandbox refused the reset" in message
    assert "For broader diagnostics, run `sase doctor -v`." in message
    assert _git(clone, "rev-parse", "HEAD").stdout.strip() == attempt_head
    assert _git(clone, "for-each-ref", "refs/sase/recovery/").stdout.strip() == ""
