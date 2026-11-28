"""Competing-checkout recovery claim publication tests.

Split from ``tests.test_bead.test_recovery_claims``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.bead._sync_publication import PushOutcome
from sase.bead.recovery import (
    REASON_EXISTING_CLAIM,
    REASON_NOT_LOCAL_WINNER,
    _publish_recovery_claim_in_store,
)
from tests.test_bead._recovery_claims_helpers import (
    FakeRecoveryCore,
    claim_request,
    recovery_fake_core,  # noqa: F401 (registers the fake_core fixture)
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _configure_git(path: Path) -> None:
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _configure_git(path)
    _git(path, "commit", "--allow-empty", "-m", "init")


def _fixture_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    first = tmp_path / "first"
    _init_repo(first)
    beads = first / "beads"
    beads.mkdir()
    (beads / "issues.jsonl").write_text("\n", encoding="utf-8")
    _git(first, "add", "beads")
    _git(first, "commit", "-m", "beads")
    _git(first, "remote", "add", "origin", str(remote))
    branch = _git(first, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    _git(first, "push", "-u", "origin", branch)
    second = tmp_path / "second"
    _git(tmp_path, "clone", str(remote), str(second))
    _configure_git(second)
    return first / "beads", second / "beads", remote


def _commit_recovery(beads_dir: Path, message: str) -> bool:
    repo = beads_dir.parent
    _git(repo, "add", "beads/recovery")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return False
    _git(repo, "commit", "-m", message)
    return True


def _push_recovery(beads_dir: Path) -> PushOutcome:
    repo = beads_dir.parent
    result = subprocess.run(
        ["git", "push"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return PushOutcome(pushed=True, skipped_no_remote=False, error=None)
    return PushOutcome(
        pushed=False,
        skipped_no_remote=False,
        error=(result.stderr or result.stdout).strip(),
    )


def _replay_recovery(beads_dir: Path) -> str | None:
    repo = beads_dir.parent
    fetched = subprocess.run(
        ["git", "fetch"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0:
        return fetched.stderr.strip()
    reset = subprocess.run(
        ["git", "reset", "--hard", "@{upstream}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if reset.returncode != 0:
        return reset.stderr.strip()
    return None


def test_competing_publisher_checkouts_keep_one_winner(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    first, second, _remote = _fixture_clones(tmp_path)
    fake_core.arm(
        str(first),
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
    )
    _commit_recovery(first, "arm")
    _push_recovery(first)
    _replay_recovery(second)

    winner = _publish_recovery_claim_in_store(
        first,
        claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert winner.launch_permit is True
    assert winner.claim is not None
    assert winner.claim.owner_machine == "athena"

    loser = _publish_recovery_claim_in_store(
        second,
        claim_request(owner="apollo", proc_id="proc-b"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert loser.launch_permit is False
    assert loser.reason in {REASON_EXISTING_CLAIM, REASON_NOT_LOCAL_WINNER}
    assert loser.claim is not None
    assert loser.claim.owner_machine == "athena"
    assert loser.claim.proc_id == "proc-a"


def test_interrupted_publication_adopts_the_published_winner(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    first, second, _remote = _fixture_clones(tmp_path)
    fake_core.arm(
        str(first),
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
    )
    _commit_recovery(first, "arm")
    _push_recovery(first)
    _replay_recovery(second)

    interrupted = _publish_recovery_claim_in_store(
        first,
        claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=lambda _path: PushOutcome(
            pushed=False, skipped_no_remote=False, error="killed"
        ),
        replay=lambda _path: "unpublished",
    )
    assert interrupted.launch_permit is False

    published = _publish_recovery_claim_in_store(
        second,
        claim_request(owner="apollo", proc_id="proc-b"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert published.launch_permit is True

    retried = _publish_recovery_claim_in_store(
        first,
        claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert retried.launch_permit is False
    assert retried.claim is not None
    assert retried.claim.owner_machine == "apollo"
