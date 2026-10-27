"""Tests for pub-measure instrumentation: timing records, lock holders, classifiers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import (
    _commit_publication_locked as publication_locked,
    git_sync_ops,
)
from sase.agents_sync._git_sync_ops_lock import _read_lock_holder
from sase.agents_sync.commit_publication_transaction import (
    DrainResult,
    PublicationTransactionHooks,
    publish_queued_transaction,
)
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox_diagnostics import (
    classify_publication_error,
)
from sase.agents_sync import publication_timing
from sase.agents_sync.publication_timing import (
    DRAIN_LOG_FILENAME,
    DrainTiming,
    emit_drain_timing,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def _target(tmp_path: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="sase",
        project="Sase",
        primary_checkout=tmp_path / "primary",
        primary_roots=(tmp_path / "primary",),
        sidecar_path=tmp_path / "sidecar",
        remote_url="https://example.invalid/sase.git",
    )


def test_drain_timing_record_stage_accumulates() -> None:
    timer = DrainTiming(project_key="sase")
    with timer.record_stage("inventory_build"):
        pass
    with timer.record_stage("inventory_build"):
        pass
    assert timer.stage == "inventory_build"
    assert timer.stage_durations["inventory_build"] >= 0.0
    record = timer.to_json_dict()
    assert record["schema_version"] == 1
    assert record["project_key"] == "sase"
    assert record["alarm_fired"] is False
    assert record["alarm_stage"] is None
    assert record["error_class"] is None


def test_drain_timing_error_class_derives_from_error() -> None:
    timer = DrainTiming(project_key="sase", error="agents sync lock is busy")
    assert timer.to_json_dict()["error_class"] == "lock_busy"
    timer = DrainTiming(
        project_key="sase",
        error="agent-hood publication did not complete within 120s",
        error_class="timeout",
    )
    assert timer.to_json_dict()["error_class"] == "timeout"


def test_emit_drain_timing_appends_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / DRAIN_LOG_FILENAME
    emit_drain_timing(
        DrainTiming(project_key="sase", outcome="no_requests"), log_path=log_path
    )
    emit_drain_timing(
        DrainTiming(project_key="bob-cli", outcome="published", active_requests=2),
        log_path=log_path,
    )
    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["project_key"] for row in rows] == ["sase", "bob-cli"]
    assert rows[0]["outcome"] == "no_requests"
    assert rows[1]["active_requests"] == 2


def test_emit_drain_timing_rotates_past_one_mib(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / DRAIN_LOG_FILENAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"x" * (1_000_000 + 8))
    emit_drain_timing(DrainTiming(project_key="sase"), log_path=log_path)
    backup = log_path.with_name(f"{log_path.name}.1")
    assert backup.is_file()
    assert backup.stat().st_size > 1_000_000
    assert log_path.stat().st_size < 1_000_000


def test_emit_drain_timing_never_raises(tmp_path: Path) -> None:
    emit_drain_timing(
        DrainTiming(project_key="sase"),
        log_path=tmp_path / "nope" / "\0" / DRAIN_LOG_FILENAME,
    )


def test_drain_log_path_honors_sase_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    assert (
        publication_timing._drain_log_path()
        == tmp_path / "state" / "logs" / DRAIN_LOG_FILENAME
    )


def test_bounded_agents_lock_writes_and_clears_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "sase-1nf.9")
    lock_path = tmp_path / "sase-agents-sync.lock"
    holder_path = tmp_path / "sase-agents-sync.lock.holder"
    with git_sync_ops.bounded_agents_lock(
        lock_path, 1.0, operation="commit-publication-drain"
    ) as acquired:
        assert acquired is True
        assert holder_path.is_file()
        holder = _read_lock_holder(lock_path)
        assert holder is not None
        assert holder.pid == os.getpid()
        assert holder.operation == "commit-publication-drain"
        assert holder.agent == "sase-1nf.9"
        diagnostic = git_sync_ops.lock_holder_diagnostic(lock_path)
        assert diagnostic is not None
        assert f"pid {os.getpid()}" in diagnostic
        assert "commit-publication-drain" in diagnostic
    assert not holder_path.exists()
    assert _read_lock_holder(lock_path) is None
    assert git_sync_ops.lock_holder_diagnostic(lock_path) is None


def test_read_lock_holder_ignores_stale_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / "sase-agents-sync.lock"
    holder_path = tmp_path / "sase-agents-sync.lock.holder"
    holder_path.write_text(
        json.dumps({"pid": 2**30, "operation": "x", "started_at": 1.0}),
        encoding="utf-8",
    )
    assert _read_lock_holder(lock_path) is None


def test_read_lock_holder_ignores_malformed_record(tmp_path: Path) -> None:
    lock_path = tmp_path / "sase-agents-sync.lock"
    holder_path = tmp_path / "sase-agents-sync.lock.holder"
    holder_path.write_text("not json", encoding="utf-8")
    assert _read_lock_holder(lock_path) is None
    assert git_sync_ops.lock_holder_diagnostic(lock_path) is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, "unknown"),
        ("", "unknown"),
        ("agent-hood publication did not complete within 120s", "timeout"),
        ("agents sync lock is busy", "lock_busy"),
        ("agents sync lock is busy; lock holder: pid 1, age 3s", "lock_busy"),
        ("agents sync clone lock is busy", "lock_busy"),
        ("could not stage: .git/index.lock exists", "index_lock"),
        ("git pull --rebase failed: unstaged changes", "unstaged_changes"),
        ("error: Your index contains uncommitted changes.", "unstaged_changes"),
        ("rebase conflict on agents/alice/page.md", "rebase_conflict"),
        ("publication payload exceeds the byte limit", "manifest_mismatch"),
        ("owner manifest does not decode", "manifest_mismatch"),
        ("weird new failure", "other"),
    ],
)
def test_classify_publication_error(error: str | None, expected: str) -> None:
    assert classify_publication_error(error) == expected


def test_counting_git_runner_counts_ops_by_name() -> None:
    timer = DrainTiming(project_key="sase")
    calls: list[str] = []

    def base(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        calls.append(op)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    runner = publication_locked._counting_git_runner(base, timer)
    runner(Path("/tmp"), ["rev-parse"], op="agents_sync.commit_record")
    runner(Path("/tmp"), ["add", "."], op="agents_sync.stage")
    assert timer.git_op_counts == {
        "agents_sync.commit_record": 1,
        "agents_sync.stage": 1,
    }
    assert calls == ["agents_sync.commit_record", "agents_sync.stage"]


def _hooks(inventory: object) -> PublicationTransactionHooks:
    def build_inventory(target: object, identity: object, **kwargs: object) -> object:
        return inventory

    return PublicationTransactionHooks(
        build_inventory=build_inventory,  # type: ignore[arg-type]
        publish_hood=lambda *args, **kwargs: None,
        update_publications=lambda *args, **kwargs: None,
        acknowledge_publications=lambda *args, **kwargs: None,
        configured_max_attempts=lambda: 3,
    )


class _Inventory:
    def __init__(self) -> None:
        self.runs: tuple[object, ...] = ()


def test_publish_queued_transaction_records_stages_with_timer(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    timer = DrainTiming(project_key="sase")

    def git_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        timer.git_op_counts[op] = timer.git_op_counts.get(op, 0) + 1
        if args[:1] == ["pull"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:1] == ["push"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem

    request = AgentPublicationOutboxItem(
        project_key="sase",
        project="Sase",
        local_agent="foo--code",
        global_agent="alice.athena.foo--code",
        primary_revision="a" * 40,
        local_hood="foo",
    )
    result = publish_queued_transaction(
        target,
        owner,
        git_runner,  # type: ignore[arg-type]
        (request,),
        hooks=_hooks(_Inventory()),
        timer=timer,
    )
    assert isinstance(result, DrainResult)
    assert "pull_rebase" in timer.stage_durations
    assert "inventory_build" in timer.stage_durations
    assert timer.runs_scanned == 0


def test_publish_queued_transaction_without_timer_is_unchanged(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")

    def git_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    result = publish_queued_transaction(
        target,
        owner,
        git_runner,  # type: ignore[arg-type]
        (),
        hooks=_hooks(_Inventory()),
    )
    assert isinstance(result, DrainResult)


def _doctor_context(tmp_path: Path):
    from sase.doctor.runner import DoctorContext

    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def _doctor_record(tmp_path: Path, *, name: str = "alpha"):
    from sase.core.project_lifecycle_wire import (
        PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        ProjectRecordWire,
    )

    project_dir = tmp_path / ".sase" / "projects" / name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / name),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def _doctor_item(
    *,
    local_agent: str = "foo--code",
    revision: str = "a" * 40,
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    created_at: float = 100.0,
    updated_at: float = 100.0,
) -> dict[str, object]:
    from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem

    hood = local_agent.split("--", 1)[0]
    return AgentPublicationOutboxItem(
        project_key="alpha",
        project="Alpha",
        local_agent=local_agent,
        global_agent=f"alice.athena.{local_agent}",
        primary_revision=revision,
        local_hood=hood,
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=updated_at if quarantined else None,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def _write_doctor_outbox(
    root: Path, project_key: str, rows: list[dict[str, object]]
) -> None:
    from sase.agents_sync.publication_outbox import (
        PUBLICATION_OUTBOX_SCHEMA_VERSION,
    )

    path = root / "projects" / project_key / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": PUBLICATION_OUTBOX_SCHEMA_VERSION, "items": rows}
        ),
        encoding="utf-8",
    )


def test_doctor_reports_error_histogram_and_oldest_active_age(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.models import TargetSelection
    from sase.doctor import checks_agent_publication_outbox as doctor_module
    from sase.doctor import checks_agent_publication_sidecar as sidecar_module
    from sase.doctor.checks_agent_publication_outbox import (
        check_agent_publication_outbox,
    )

    monkeypatch.setattr(
        doctor_module,
        "list_project_records",
        lambda *_args, **_kwargs: [_doctor_record(tmp_path)],
    )
    monkeypatch.setattr(
        sidecar_module,
        "resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((), ()),
    )
    now = 10_000.0
    _write_doctor_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            _doctor_item(
                local_agent="bad--code",
                revision="b" * 40,
                attempts=3,
                last_error="agents sync lock is busy",
                quarantined=True,
                created_at=now - 120,
                updated_at=now - 60,
            ),
            _doctor_item(
                local_agent="slow--code",
                revision="c" * 40,
                attempts=1,
                last_error="agent-hood publication did not complete within 120s",
                created_at=now - 500,
                updated_at=now - 60,
            ),
        ],
    )

    check = check_agent_publication_outbox(_doctor_context(tmp_path), now=now)

    assert check.data["last_error_histogram"] == {
        "lock_busy": 1,
        "timeout": 1,
    }
    assert check.data["oldest_active_age_seconds"] == pytest.approx(500.0)
    assert check.data["sidecar_states"] == ()


def test_doctor_oldest_active_age_is_none_without_active_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.models import TargetSelection
    from sase.doctor import checks_agent_publication_outbox as doctor_module
    from sase.doctor import checks_agent_publication_sidecar as sidecar_module
    from sase.doctor.checks_agent_publication_outbox import (
        check_agent_publication_outbox,
    )

    monkeypatch.setattr(
        doctor_module,
        "list_project_records",
        lambda *_args, **_kwargs: [_doctor_record(tmp_path)],
    )
    monkeypatch.setattr(
        sidecar_module,
        "resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((), ()),
    )
    _write_doctor_outbox(tmp_path / ".sase", "alpha", [])

    check = check_agent_publication_outbox(_doctor_context(tmp_path), now=200.0)

    assert check.data["last_error_histogram"] == {}
    assert check.data["oldest_active_age_seconds"] is None


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_sidecar_state_reports_ahead_and_dirty_payload(
    tmp_path: Path,
) -> None:
    from sase.doctor.checks_agent_publication_sidecar import _sidecar_state

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], cwd=tmp_path, check=True
    )
    clone = tmp_path / "sidecar"
    _init_git_repo(clone)
    (clone / "agents").mkdir()
    (clone / "agents" / "page.md").write_text("hood\n", encoding="utf-8")
    (clone / "prompts").mkdir()
    (clone / "prompts" / "doc.md").write_text("prompt\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=clone, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)], cwd=clone, check=True
    )
    subprocess.run(["git", "push", "-q", "-u", "origin", "HEAD"], cwd=clone, check=True)
    # One unpushed commit plus dirty prompts and untracked objects.
    (clone / "agents" / "page.md").write_text("hood v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "second"], cwd=clone, check=True)
    (clone / "prompts" / "doc.md").write_text("prompt v2\n", encoding="utf-8")
    (clone / "files").mkdir()
    (clone / "files" / "objects").mkdir(parents=True)
    (clone / "files" / "objects" / "blob.bin").write_bytes(b"\0" * 16)

    state = _sidecar_state("sase", "Sase", clone)

    assert state["status"] == "ok"
    assert state["ahead"] == 1
    assert state["behind"] == 0
    assert state["rebase_in_progress"] is False
    assert state["untracked_objects"] == 1
    assert state["dirty_prompts"] == 1
    assert state["dirty_artifacts"] == 0


def test_sidecar_state_reports_missing_clone(tmp_path: Path) -> None:
    from sase.doctor.checks_agent_publication_sidecar import _sidecar_state

    state = _sidecar_state("sase", "Sase", tmp_path / "nope")
    assert state["status"] == "missing"
