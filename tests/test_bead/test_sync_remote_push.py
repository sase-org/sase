"""Tests for pushing remote bead work."""

from __future__ import annotations

import subprocess

from sase.bead.sync import _PushOutcome, publish_bead_claim, push_bead_work_launch
from sase.bead.sync_worker import _ManagedSyncOutcome

from .sync_test_helpers import configure_git_identity, init_git_repo


def test_push_bead_work_launch_treats_locked_worker_as_published_when_head_is_remote(
    tmp_path,
    monkeypatch,
):
    repo = _repo_with_upstream(tmp_path)
    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"published"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "published bead state"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "fetch"], cwd=repo, capture_output=True, check=True)
    monkeypatch.setattr(
        "sase.bead.sync_worker.run_managed_sync_worker",
        lambda *_args, **_kwargs: _ManagedSyncOutcome(
            pushed=False,
            integrated=False,
            skipped_locked=True,
        ),
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.skipped_locked is False
    assert outcome.error is None


def test_push_bead_work_launch_reports_locked_worker_without_error_when_unpublished(
    tmp_path,
    monkeypatch,
):
    repo = _repo_with_upstream(tmp_path)
    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"local"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "local bead state"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    monkeypatch.setattr(
        "sase.bead.sync_worker.run_managed_sync_worker",
        lambda *_args, **_kwargs: _ManagedSyncOutcome(
            pushed=False,
            integrated=False,
            skipped_locked=True,
        ),
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_locked is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None


def test_push_bead_work_launch_no_error_worker_failure_mentions_log_path(
    tmp_path,
    monkeypatch,
):
    repo = _repo_with_upstream(tmp_path)
    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.bead.sync_worker.run_managed_sync_worker",
        lambda *_args, **_kwargs: _ManagedSyncOutcome(
            pushed=False,
            integrated=False,
            error=None,
        ),
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "managed bead sync did not push and reported no error" in outcome.error
    assert outcome.log_path is not None
    assert str(outcome.log_path) in outcome.error


def test_publish_bead_claim_suppresses_locked_skip_warning_but_keeps_real_warning(
    tmp_path,
    monkeypatch,
    capsys,
):
    beads_dir = tmp_path / ".sase/sdd/beads"
    beads_dir.mkdir(parents=True)
    log_path = tmp_path / "sync.log"
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=None,
            skipped_locked=True,
            log_path=log_path,
        ),
    )

    publish_bead_claim(beads_dir, "sase-1", "worker")

    assert capsys.readouterr().err == ""

    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed",
            log_path=log_path,
        ),
    )

    publish_bead_claim(beads_dir, "sase-1", "worker")

    err = capsys.readouterr().err
    assert "Warning: Failed to publish bead claim transition" in err
    assert "git push failed" in err


def test_push_bead_work_launch_skips_when_no_remote(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_skips_outside_git_repo(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_returns_error_when_git_root_probe_raises(
    tmp_path,
    monkeypatch,
):
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.setattr(
        "sase.bead.sync._find_git_root",
        lambda _beads_dir: (_ for _ in ()).throw(
            RuntimeError("timed out probing git root")
        ),
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is False
    assert outcome.error == "timed out probing git root"


def test_push_bead_work_launch_pushes_to_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None

    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    remote_head = subprocess.run(
        ["git", "rev-parse", f"refs/heads/{branch}"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_head == remote_head


def test_push_bead_work_launch_rebases_and_retries_rejected_push(tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=seed,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=seed,
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "clone", str(bare), str(other)], capture_output=True, check=True
    )
    configure_git_identity(repo)
    configure_git_identity(other)

    (other / "remote.md").write_text("remote\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "remote.md"], cwd=other, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "remote change"],
        cwd=other,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"local"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "local bead change"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    from sase.sdd._repository_health import default_git_runner

    raced = False

    def push_remote_just_before_local_push(repo_root, args, *, op, network=False):
        nonlocal raced
        if args == ["push"] and not raced:
            raced = True
            subprocess.run(
                ["git", "push"],
                cwd=other,
                capture_output=True,
                check=True,
            )
        return default_git_runner(
            repo_root,
            args,
            op=op,
            network=network,
        )

    monkeypatch.setattr(
        "sase.bead.sync_worker._git",
        push_remote_just_before_local_push,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None
    assert raced is True
    assert (repo / "remote.md").read_text(encoding="utf-8") == "remote\n"

    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(bare), str(verify)],
        capture_output=True,
        check=True,
    )
    assert (verify / "remote.md").read_text(encoding="utf-8") == "remote\n"
    assert (verify / "sdd/beads/issues.jsonl").read_text(encoding="utf-8") == (
        '{"id":"local"}\n'
    )


def test_push_bead_work_launch_returns_error_on_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "does-not-exist.git")],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is False
    assert outcome.error is not None
    assert "git fetch failed" in outcome.error


def _repo_with_upstream(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        capture_output=True,
        check=True,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo
