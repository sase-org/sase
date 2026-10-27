"""GH013 push-rejection recovery across every agents-sidecar push path.

Uses real temporary git repositories, the real Rust rejection classifier and
protection ledger, and a fake push runner that simulates remote secret
scanning. A synthetic token stands in for secret bytes: it must never appear
in any error, diagnostic, or ledger payload.
"""

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
    record_publication_push_rejection,
)

TOKEN = "SYNTHETIC-REMOTE-SECRET-7f3a9c2e"
BLOCKED_REL = "agents/local.athena.worker/chat.md"
SECOND_BLOCKED_REL = "agents/local.athena.worker/prompt.md"
CLEAN_REL = "agents/local.athena.other/chat.md"


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-b", "main")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    git(sidecar, "config", "user.name", "Tests")
    git(sidecar, "config", "user.email", "tests@example.test")
    (sidecar / "README.md").write_text("# sidecar\n")
    git(sidecar, "add", "README.md")
    git(sidecar, "commit", "-m", "seed")
    git(sidecar, "push", "-u", "origin", "HEAD:main")
    return remote, sidecar


def commit(sidecar: Path, relpath: str, content: bytes, message: str) -> None:
    path = sidecar / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    git(sidecar, "add", relpath)
    git(sidecar, "commit", "-m", message)


def tip(sidecar: Path) -> str:
    return git(sidecar, "rev-parse", "HEAD").stdout.strip()


def upstream_tip(sidecar: Path) -> str:
    return git(sidecar, "rev-parse", "@{upstream}").stdout.strip()


def isolate_protection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state = tmp_path / "state"
    projects_root = state / "projects"

    import sase.agents_sync.publication_protection as protection
    import sase.agents_sync.prompt_archive.protection as archive_protection

    monkeypatch.setattr(protection, "sase_home", lambda: state)
    monkeypatch.setattr(protection, "sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(archive_protection, "sase_home", lambda: state)
    return state


def gh013_stderr(*paths: str, token: str = TOKEN) -> str:
    lines = [
        "remote: error: GH013: Repository rule violations found for refs/heads/main.",
        f"remote: error: {token}",
        "remote: error: The following lines were detected as secrets:",
    ]
    lines.extend(f"remote: error:   path: {path}" for path in paths)
    lines.append("remote: error: Push cannot contain secrets.")
    lines.append("To " + "https://example.test/remote.git")
    lines.append(" ! [remote rejected] main -> main (push declined due to secret)")
    lines.append("error: failed to push some refs to 'https://example.test/remote.git'")
    return "\n".join(lines) + "\n"


def scope_for(remote: Path) -> PublicationProtectionScope:
    return PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )


def recover(
    sidecar: Path,
    runner,  # noqa: ANN001 - tests use duck-typed git runners.
    scope: PublicationProtectionScope,
    stderr: str,
    *,
    affected: tuple[tuple[str, str], ...] = (),
) -> recovery.PublicationPushRecovery:
    return recovery.recover_publication_push(
        sidecar,
        runner,
        project_key=scope.project_key,
        repository_identity=scope.repository_identity,
        returncode=1,
        stdout="",
        stderr=stderr,
        affected_requests=affected,
    )


def test_secret_scan_precedes_fetch_first_hints() -> None:
    rejection = recovery.classify_publication_push(
        returncode=1,
        stdout="",
        stderr=gh013_stderr(BLOCKED_REL) + "update rejected: fetch first\n",
    )
    assert rejection.classification == recovery.REJECTED_SECRET_SCAN
    assert rejection.relative_paths == (BLOCKED_REL,)


def test_push_cannot_contain_secrets_is_a_secret_rejection() -> None:
    rejection = recovery.classify_publication_push(
        returncode=1, stdout="", stderr="remote: Push cannot contain secrets.\n"
    )
    assert rejection.classification == recovery.REJECTED_SECRET_SCAN


def test_empty_push_output_is_an_unattributed_unknown() -> None:
    rejection = recovery.classify_publication_push(returncode=1, stdout="", stderr="")
    assert rejection.classification == "unknown_failure"
    assert rejection.relative_paths == ()


def test_classifier_failure_degrades_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.sidecar_publication_facade as facade

    def missing_binding(_name: str) -> object:
        raise RuntimeError("sase_core_rs is unavailable")

    monkeypatch.setattr(facade, "require_rust_binding", missing_binding)
    rejection = recovery.classify_publication_push(
        returncode=1, stdout="", stderr=gh013_stderr(BLOCKED_REL)
    )
    assert rejection.classification == "unknown_failure"
    assert rejection.relative_paths == ()


def test_sanitized_secret_error_names_paths_but_never_the_token() -> None:
    rejection = recovery.PublicationPushRejection(
        recovery.REJECTED_SECRET_SCAN, (), (BLOCKED_REL,)
    )
    message = recovery.sanitized_push_error("git push failed", rejection)
    assert BLOCKED_REL in message
    assert TOKEN not in message
    assert "GH013" in message or "secret scanning" in message


def test_sanitized_rule_error_confirms_no_secret() -> None:
    rejection = recovery.PublicationPushRejection(
        recovery.REJECTED_REPOSITORY_RULE, (), ()
    )
    message = recovery.sanitized_push_error("git push failed", rejection)
    assert "no secret was confirmed" in message


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


def _gated_run(prompt_bytes: bytes):
    from sase.agents_sync.inventory_models import InventoryRun
    from sase.core.agent_identity_facade import AgentOwnerIdentity
    from sase.agents_sync.v2_models import V2ProjectIdentity

    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = InventoryRun(
        "run-1",
        "worker",
        "alice.athena.worker",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        prompt_bytes,
        b"clean chat\n",
        None,
        None,
        (),
        "20260723120000",
    )
    return run, owner, project


def test_snapshot_regeneration_withholds_rejection_blocked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import _gate_run_files

    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity="https://example.test/sidecar.git"
    )
    prompt_bytes = b"ordinary prompt the remote rejected\n"
    digest = hashlib.sha256(prompt_bytes).hexdigest()
    destination = "agents/alice.athena.worker/prompt.md"
    assert (
        record_publication_push_rejection(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            sha256=digest,
            classification=recovery.REJECTED_SECRET_SCAN,
        )
        is not None
    )

    run, owner, project = _gated_run(prompt_bytes)
    payload: dict[str, bytes] = {}
    gated = _gate_run_files(run, owner, project, payload, scope=scope)

    assert gated.record is not None
    assert destination not in payload
    assert "prompt" in gated.blocked_kinds
    assert any("blocked" in note for note in gated.notes)


def test_snapshot_regeneration_publishes_unblocked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import _gate_run_files

    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity="https://example.test/sidecar.git"
    )
    prompt_bytes = b"ordinary prompt nobody rejected\n"

    run, owner, project = _gated_run(prompt_bytes)
    payload: dict[str, bytes] = {}
    gated = _gate_run_files(run, owner, project, payload, scope=scope)

    assert gated.record is not None
    assert payload["agents/alice.athena.worker/prompt.md"] == prompt_bytes


def test_pre_stage_verification_withholds_rejection_blocked_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync._git_sync_ops_payload import (
        _verify_agents_payload_protection,
    )
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    rel = "agents/local.athena.worker/chat.md"
    commit(sidecar, rel, b"previously published bytes\n", "baseline")
    blocked_bytes = b"rejected bytes returned through another path\n"
    (sidecar / rel).write_bytes(blocked_bytes)
    assert (
        record_publication_push_rejection(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=rel,
            sha256=hashlib.sha256(blocked_bytes).hexdigest(),
            classification=recovery.REJECTED_SECRET_SCAN,
        )
        is not None
    )

    error = _verify_agents_payload_protection(sidecar, run_git, scope=scope)

    assert error is not None and "withheld" in error


def test_pre_stage_verification_passes_unblocked_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync._git_sync_ops_payload import (
        _verify_agents_payload_protection,
    )
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    candidate = sidecar / CLEAN_REL
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"ordinary clean bytes\n")

    assert _verify_agents_payload_protection(sidecar, run_git, scope=scope) is None


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


def _gh013_push_runner(rejections: int, stderr: str):
    from sase.agents_sync.git import run_git

    calls: list[int] = []

    def runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            calls.append(1)
            if len(calls) <= rejections:
                return subprocess.CompletedProcess(args, 1, "", stderr)
        return run_git(cwd, args, network=network, op=op)

    return runner, calls


def test_full_sync_recovers_from_gh013_and_publishes_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import git_sync
    from sase.agents_sync.v2_models import V2PublicationCounts
    from tests.agents_sync.git_sync_fixtures import (
        setup_repo as setup_sync_repo,
    )
    from tests.agents_sync.git_sync_fixtures import (
        target as make_target,
    )

    remote, _seed, sidecar = setup_sync_repo(tmp_path)
    sync_target = make_target(tmp_path, remote, sidecar)
    isolate_protection(monkeypatch, tmp_path)
    blocked_rel = "agents/local.athena.worker/notes.md"
    first_bytes = b"rollout note the remote rejected\n"
    second_bytes = b"rollout note sanitized for publication\n"
    calls: list[int] = []

    def reconcile(_target, repo: Path, **_kwargs) -> V2PublicationCounts:
        calls.append(1)
        (repo / "README.md").write_text("# Hoods\n")
        (repo / "schema.json").write_text("{}\n")
        bundle = repo / "agents" / "local.athena.worker"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "notes.md").write_bytes(
            first_bytes if len(calls) == 1 else second_bytes
        )
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
        return V2PublicationCounts(hoods_published=1, runs_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    runner, push_calls = _gh013_push_runner(1, gh013_stderr(blocked_rel))

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=runner)

    assert outcome.error is None
    assert outcome.pushed and outcome.push_attempts == 2
    assert len(push_calls) == 2 and len(calls) == 2
    check = tmp_path / "check"
    git(tmp_path, "clone", str(remote), str(check))
    assert (check / blocked_rel).read_bytes() == second_bytes
    missing = subprocess.run(
        ["git", "grep", "-l", "remote rejected", "HEAD"],
        cwd=check,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1
    assert TOKEN not in repr(outcome)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )
    assert not publication_content_retry_allowed(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=blocked_rel,
        sha256=hashlib.sha256(first_bytes).hexdigest(),
    )


def test_commit_drain_recovers_from_gh013_and_rebuilds_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.commit_publication_transaction import (
        PublicationTransactionHooks,
        publish_queued_transaction,
    )
    from sase.agents_sync.inventory import ProjectHoodInventory
    from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem
    from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
    from sase.agents_sync.v2_models import (
        V2OwnerHoodEntry,
        V2OwnerManifest,
        V2ProjectIdentity,
        V2PublicationCounts,
    )
    from sase.core.agent_identity_facade import AgentOwnerIdentity
    from tests.agents_sync.commit_publication_fixtures import setup_target

    target, remote = setup_target(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    first = b"hood page the remote rejected\n"
    second = b"hood page sanitized\n"
    writes: list[int] = []

    def publish_hood(_target, repo: Path, _agent: str, **_kwargs) -> object:
        writes.append(1)
        (repo / "README.md").write_bytes(first if len(writes) == 1 else second)
        (repo / "schema.json").write_text("{}\n")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    updated: list[tuple[tuple[object, ...], dict[str, object]]] = []
    hooks = PublicationTransactionHooks(
        build_inventory=lambda *args, **kwargs: ProjectHoodInventory(owner, "proj", ()),
        publish_hood=publish_hood,
        update_publications=lambda *args, **kwargs: updated.append((args, kwargs)),
        acknowledge_publications=lambda *args, **kwargs: None,
        configured_max_attempts=lambda: 5,
    )
    runner, push_calls = _gh013_push_runner(1, gh013_stderr("README.md"))
    request = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo",
        global_agent="alice.athena.foo",
        primary_revision="a" * 40,
        local_hood="foo",
    )

    result = publish_queued_transaction(target, owner, runner, (request,), hooks=hooks)

    assert result.error is None
    assert len(push_calls) == 2 and len(writes) == 2
    check = tmp_path / "check"
    git(tmp_path, "clone", str(remote), str(check))
    assert (check / "README.md").read_bytes() == second
    assert TOKEN not in repr(result)
    assert not publication_content_retry_allowed(
        "proj",
        repository_identity=str(remote),
        relative_destination="README.md",
        sha256=hashlib.sha256(first).hexdigest(),
    )


def test_prompt_publish_gh013_resets_and_sanitizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git
    from sase.agents_sync.prompt_archive.publish import (
        _classify_prompt_archive_push_error,
    )

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )
    rel = "prompts/alice.athena.worker/prompt.md"
    content = b"prompt the remote rejected\n"
    commit(sidecar, rel, content, "prompt unit")
    base_tip = upstream_tip(sidecar)
    pushed = subprocess.CompletedProcess(["push"], 1, "", gh013_stderr(rel))

    message = _classify_prompt_archive_push_error(sidecar, run_git, pushed, scope)

    assert TOKEN not in message and rel in message
    assert tip(sidecar) == base_tip
    record = lookup_publication_content_record(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=rel,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"


def test_migration_push_detail_sanitizes_secret_rejections() -> None:
    from sase.agents_sync.prompt_archive.migration import (
        _sanitized_migration_push_detail,
    )

    rejected = subprocess.CompletedProcess(
        ["push", "origin", "HEAD"], 1, "", gh013_stderr("prompts/past.md")
    )
    detail = _sanitized_migration_push_detail(rejected)
    assert TOKEN not in detail
    assert "secret scanning" in detail

    generic = subprocess.CompletedProcess(
        ["push", "origin", "HEAD"], 1, "", "planned push failure"
    )
    assert _sanitized_migration_push_detail(generic) == "planned push failure"
