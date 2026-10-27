"""Secret-rejection blocking, reset, and idempotent recovery tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import publication_recovery as recovery
from sase.agents_sync.publication_protection import (
    PublicationProtectionScope,
    lookup_publication_content_record,
    publication_content_retry_allowed,
)
from tests.agents_sync.test_publication_recovery._helpers import (
    BLOCKED_REL,
    CLEAN_REL,
    SECOND_BLOCKED_REL,
    TOKEN,
    commit,
    gh013_stderr,
    git,
    isolate_protection,
    recover,
    scope_for,
    setup_repo,
    tip,
    upstream_tip,
)


def test_secret_rejection_blocks_paths_and_resets_to_upstream_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    blocked_bytes = b"clean locally but rejected remotely\n"
    clean_bytes = b"ordinary clean bytes\n"
    commit(sidecar, BLOCKED_REL, blocked_bytes, "blocked unit")
    commit(sidecar, CLEAN_REL, clean_bytes, "clean unit")
    expected_digest = hashlib.sha256(blocked_bytes).hexdigest()
    base_tip = upstream_tip(sidecar)

    result = recover(sidecar, run_git, scope, gh013_stderr(BLOCKED_REL))

    assert result.action == recovery.RECOVERY_REBUILD_CLEAN
    assert result.blocked_paths == (BLOCKED_REL,)
    assert tip(sidecar) == base_tip
    record = lookup_publication_content_record(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=BLOCKED_REL,
        sha256=expected_digest,
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"
    assert not publication_content_retry_allowed(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=BLOCKED_REL,
        sha256=expected_digest,
    )
    assert (
        lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=CLEAN_REL,
            sha256=hashlib.sha256(clean_bytes).hexdigest(),
        )
        is None
    )
    for path in (tmp_path / "state" / "projects" / "proj").glob("*"):
        assert TOKEN not in path.read_text(encoding="utf-8")


def test_no_location_rejection_resets_without_blaming_a_clean_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    commit(sidecar, CLEAN_REL, b"clean bytes\n", "clean unit")
    base_tip = upstream_tip(sidecar)

    result = recover(sidecar, run_git, scope, gh013_stderr())

    assert result.action == recovery.RECOVERY_REBUILD_CLEAN
    assert result.blocked_paths == ()
    assert tip(sidecar) == base_tip
    projects = tmp_path / "state" / "projects" / "proj"
    assert not projects.exists() or (
        lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=CLEAN_REL,
            sha256=hashlib.sha256(b"clean bytes\n").hexdigest(),
        )
        is None
    )


def test_multiple_offending_units_are_all_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    first = b"first rejected unit\n"
    second = b"second rejected unit\n"
    commit(sidecar, BLOCKED_REL, first, "first")
    commit(sidecar, SECOND_BLOCKED_REL, second, "second")

    result = recover(
        sidecar, run_git, scope, gh013_stderr(BLOCKED_REL, SECOND_BLOCKED_REL)
    )

    assert result.action == recovery.RECOVERY_REBUILD_CLEAN
    assert set(result.blocked_paths) == {BLOCKED_REL, SECOND_BLOCKED_REL}
    for rel, content in ((BLOCKED_REL, first), (SECOND_BLOCKED_REL, second)):
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=rel,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        assert isinstance(record, dict) and record.get("status") == "blocked"


def test_older_commit_bytes_and_early_objects_are_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    state = isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    object_bytes = b"sole-copy captured object\n"
    object_digest = hashlib.sha256(object_bytes).hexdigest()
    object_rel = f"files/objects/{object_digest[:2]}/{object_digest}"
    commit(sidecar, BLOCKED_REL, b"older rejected bytes\n", "older batch")
    commit(sidecar, object_rel, object_bytes, "early object commit")
    commit(sidecar, CLEAN_REL, b"tip clean bytes\n", "tip batch")
    base_tip = upstream_tip(sidecar)

    result = recover(sidecar, run_git, scope, gh013_stderr(BLOCKED_REL))

    assert result.action == recovery.RECOVERY_REBUILD_CLEAN
    assert tip(sidecar) == base_tip
    assert result.preserved_paths == (object_rel,)
    preserved = state / "private" / "agents-publication-recovery" / "proj"
    copies = list(preserved.rglob(object_digest))
    assert len(copies) == 1
    assert hashlib.sha256(copies[0].read_bytes()).hexdigest() == object_digest
    # The blocked bytes sat in an older commit, not the tip tree, and are
    # still blocked by digest.
    record = lookup_publication_content_record(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=BLOCKED_REL,
        sha256=hashlib.sha256(b"older rejected bytes\n").hexdigest(),
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"


def test_repository_rule_is_sanitized_without_reset_or_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    commit(sidecar, CLEAN_REL, b"clean bytes\n", "clean unit")
    ahead = tip(sidecar)
    stderr = (
        "remote: Repository rule violation: signed commits required\n"
        f"remote: details: {TOKEN}\n"
        "! [remote rejected] main -> main (repository rule violation)\n"
    )

    result = recover(sidecar, run_git, scope, stderr)

    assert result.rejection.classification == recovery.REJECTED_REPOSITORY_RULE
    assert result.action == recovery.RECOVERY_STOP
    assert tip(sidecar) == ahead
    message = recovery.sanitized_push_error("git push failed", result.rejection)
    assert TOKEN not in message
    assert "no secret was confirmed" in message


def test_unknown_failure_stops_without_reset_or_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    commit(sidecar, CLEAN_REL, b"clean bytes\n", "clean unit")
    ahead = tip(sidecar)

    result = recover(sidecar, run_git, scope, "fatal: connection reset\n")

    assert result.rejection.classification == "unknown_failure"
    assert result.action == recovery.RECOVERY_STOP
    assert tip(sidecar) == ahead


def test_fetch_failure_leaves_the_batch_but_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    blocked_bytes = b"rejected remotely\n"
    commit(sidecar, BLOCKED_REL, blocked_bytes, "blocked unit")
    ahead = tip(sidecar)

    def failing_fetch(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["fetch"]:
            return subprocess.CompletedProcess(args, 1, "", "network is down")
        return run_git(cwd, args, network=network, op=op)

    result = recover(sidecar, failing_fetch, scope, gh013_stderr(BLOCKED_REL))

    assert result.action == recovery.RECOVERY_STOP
    assert tip(sidecar) == ahead
    assert result.blocked_paths == (BLOCKED_REL,)
    assert result.error is not None and TOKEN not in result.error


def test_reset_refuses_a_foreign_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    blocked_bytes = b"rejected remotely\n"
    commit(sidecar, BLOCKED_REL, blocked_bytes, "blocked unit")
    ahead = tip(sidecar)
    foreign = PublicationProtectionScope(
        project_key="proj", repository_identity="https://example.test/other.git"
    )

    result = recover(sidecar, run_git, foreign, gh013_stderr(BLOCKED_REL))

    assert result.action == recovery.RECOVERY_STOP
    assert tip(sidecar) == ahead
    assert result.error is not None and "refused" in result.error
    # Attribution still landed before the refused reset.
    record = lookup_publication_content_record(
        foreign.project_key,
        repository_identity=foreign.repository_identity,
        relative_destination=BLOCKED_REL,
        sha256=hashlib.sha256(blocked_bytes).hexdigest(),
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"


def test_interrupted_recovery_resumes_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    blocked_bytes = b"rejected bytes\n"
    commit(sidecar, BLOCKED_REL, blocked_bytes, "blocked unit")
    digest = hashlib.sha256(blocked_bytes).hexdigest()

    first = recover(sidecar, run_git, scope, gh013_stderr(BLOCKED_REL))
    assert first.action == recovery.RECOVERY_REBUILD_CLEAN
    # A resumed attempt after the reset finds an empty outgoing range, keeps
    # the durable block, and resets to the same tip without failing.
    second = recover(sidecar, run_git, scope, gh013_stderr(BLOCKED_REL))
    assert second.action == recovery.RECOVERY_REBUILD_CLEAN
    assert tip(sidecar) == upstream_tip(sidecar)
    record = lookup_publication_content_record(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=BLOCKED_REL,
        sha256=digest,
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"


def test_concurrent_upstream_movement_survives_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    commit(sidecar, BLOCKED_REL, b"rejected bytes\n", "blocked unit")
    intruder = tmp_path / "intruder"
    git(tmp_path, "clone", str(remote), str(intruder))
    git(intruder, "config", "user.name", "Intruder")
    git(intruder, "config", "user.email", "intruder@example.test")
    (intruder / "remote.txt").write_text("remote\n")
    git(intruder, "add", "remote.txt")
    git(intruder, "commit", "-m", "remote race")
    git(intruder, "push")

    result = recover(sidecar, run_git, scope, gh013_stderr(BLOCKED_REL))

    assert result.action == recovery.RECOVERY_REBUILD_CLEAN
    assert tip(sidecar) == upstream_tip(sidecar)
    assert (sidecar / "remote.txt").read_text() == "remote\n"
    assert not (sidecar / BLOCKED_REL).exists()
