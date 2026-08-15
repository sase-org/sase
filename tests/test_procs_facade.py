"""Tests for durable proc models, ids, logs, config, and Rust facade."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config import core as config_core
from sase.procs import (
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    PROC_WIRE_SCHEMA_VERSION,
    STORE_LOG_OWNER,
    TUI_PROC_KIND,
    Proc,
    ProcFinish,
    ProcAppendOutcome,
    ProcPruneOutcome,
    ProcReserve,
    ProcSettlement,
    ProcStopRequest,
    ProcRefError,
    ProcSupervisorClaim,
    ProcStoreSnapshot,
    ProcUpdate,
    ProcUpdateOutcome,
    append_proc,
    begin_proc_settlement,
    claim_proc_supervisor,
    delete_proc_logs,
    filter_procs,
    finish_proc,
    get_proc,
    new_proc_id,
    open_proc_log,
    prune_procs,
    proc_log_path,
    read_proc_log_tail,
    read_procs,
    request_proc_stop,
    resolve_proc_ref,
    reserve_proc,
    short_proc_id,
    update_proc,
)
from sase.procs.ids import PROC_ID_ALPHABET, PROC_ID_LENGTH


def _proc(
    proc_id: str,
    *,
    kind: str = "command",
    status: str = "pending",
    created_at: str = "2026-07-25T12:00:00Z",
    label: str = "Build docs",
    project: str | None = "sase",
    session_id: str | None = "session-a",
    tags: list[str] | None = None,
    command: list[str] | None = None,
    cl_name: str | None = "docs_refresh",
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=label,
        kind=kind,
        status=status,
        command=command or ["just", "docs"],
        cwd="/tmp",
        project=project,
        session_id=session_id,
        origin="test",
        cl_name=cl_name,
        tags=tags or ["docs"],
        created_at=created_at,
        log_path=f"/tmp/{proc_id}.log",
    )


def _reserve(
    proc_id: str,
    *,
    shell_name: str = "agent--build",
    fingerprint: str = "fingerprint",
    concurrency_keys: list[str] | None = None,
) -> ProcReserve:
    return ProcReserve(
        proc_id=proc_id,
        label="Build docs",
        argv=["just", "docs"],
        cwd="/tmp",
        project="sase",
        workspace_num=10,
        session_id="session-a",
        origin="test",
        tags=["docs"],
        created_at="2026-07-25T12:00:00Z",
        log_path=f"/tmp/{proc_id}.log",
        shell_name=shell_name,
        concurrency_keys=concurrency_keys or ["docs"],
        request_fingerprint=fingerprint,
        reserved_by="agent-one",
        timeout_seconds=30,
    )


def test_proc_wire_round_trip_ignores_unknown_fields() -> None:
    proc = _proc("0123456789ab")
    payload = proc.to_dict()
    payload["future_field"] = {"new": True}

    restored = Proc.from_dict(payload)

    assert restored == proc
    assert restored.to_dict()["project"] == "sase"


def test_legacy_task_wire_payloads_parse_as_proc_models() -> None:
    proc = _proc("0123456789ab")
    task_payload = proc.to_dict()
    task_payload["task_id"] = task_payload.pop("proc_id")
    snapshot_payload = {
        "schema_version": 1,
        "tasks": [task_payload],
        "stats": {},
    }

    snapshot = ProcStoreSnapshot.from_dict(snapshot_payload)
    appended = ProcAppendOutcome.from_dict(
        {
            "schema_version": 1,
            "snapshot": snapshot_payload,
            "pruned_task_ids": ["old-task"],
        }
    )
    updated = ProcUpdateOutcome.from_dict(
        {
            "schema_version": 1,
            "task": task_payload,
            "matched": True,
        }
    )
    pruned = ProcPruneOutcome.from_dict(
        {
            "schema_version": 1,
            "snapshot": snapshot_payload,
            "pruned_task_ids": ["old-task"],
        }
    )

    assert snapshot.procs == [proc]
    assert appended.pruned_proc_ids == ["old-task"]
    assert updated.proc == proc
    assert pruned.pruned_proc_ids == ["old-task"]


def test_legacy_commandless_tui_payload_receives_proc_shell_defaults() -> None:
    snapshot = ProcStoreSnapshot.from_dict(
        {
            "schema_version": 2,
            "procs": [
                {
                    "proc_id": "legacy-tui",
                    "label": "Legacy TUI",
                    "kind": TUI_PROC_KIND,
                    "status": "running",
                    "command": [],
                    "cwd": "/tmp",
                    "origin": "test",
                    "created_at": "2026-07-25T12:00:00Z",
                    "log_path": "/tmp/legacy-tui.log",
                }
            ],
            "stats": {},
        }
    )

    proc = snapshot.procs[0]
    assert proc.schema_version == 2
    assert proc.argv == []
    assert proc.log_owner == STORE_LOG_OWNER
    assert proc.lifecycle == "legacy"


def test_proc_update_distinguishes_omitted_from_explicit_null() -> None:
    update = ProcUpdate(proc_id="0123456789ab", phase=None, pid=42)

    assert update.to_dict() == {
        "proc_id": "0123456789ab",
        "pid": 42,
        "phase": None,
    }
    assert ProcUpdate.from_dict(
        {"proc_id": "0123456789ab", "phase": None, "future": "ignored"}
    ).to_dict() == {"proc_id": "0123456789ab", "phase": None}


def test_proc_id_generation_and_short_form() -> None:
    ids = {new_proc_id() for _ in range(100)}

    assert len(ids) == 100
    assert all(len(proc_id) == PROC_ID_LENGTH for proc_id in ids)
    assert all(set(proc_id) <= set(PROC_ID_ALPHABET) for proc_id in ids)
    assert short_proc_id("0123456789ab") == "012345"


def test_resolve_proc_ref_handles_unique_short_unknown_and_ambiguous() -> None:
    first = _proc("abc012345678", label="First")
    second = _proc("abc112345678", label="Second")
    procs = [first, second]

    assert resolve_proc_ref("ABC0", procs) is first
    with pytest.raises(ProcRefError, match="at least 3"):
        resolve_proc_ref("ab", procs)
    with pytest.raises(ProcRefError, match="no proc"):
        resolve_proc_ref("zzz", procs)
    with pytest.raises(ProcRefError, match=r"abc012.*First.*abc112.*Second"):
        resolve_proc_ref("abc", procs)


def test_proc_log_pipe_bounds_subprocess_output(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_PROC_LOG_MAX_BYTES", "64")

    with open_proc_log("proc-one") as output:
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; print('A' * 100); sys.stdout.flush(); "
                    "print('tail', file=sys.stderr)"
                ),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )

    path = proc_log_path("proc-one")
    assert path.stat().st_size <= 64
    assert "tail" in path.read_text(encoding="utf-8")


def test_proc_log_tail_spans_rotation_and_delete(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = proc_log_path("proc-one")
    path.parent.mkdir(parents=True)
    path.with_name(f"{path.name}.1").write_text("one\ntwo\n", encoding="utf-8")
    path.write_text("three\nfour\n", encoding="utf-8")

    assert read_proc_log_tail("proc-one", 3) == "two\nthree\nfour\n"
    delete_proc_logs(["proc-one", "missing"])
    assert not path.exists()
    assert not path.with_name(f"{path.name}.1").exists()


def test_proc_log_path_rejects_traversal(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid proc id"):
        proc_log_path("../escape")


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 100),
        ({"procs": {"history_limit": 7}}, 7),
        ({"procs": {"history_limit": 0}}, 100),
        ({"procs": {"history_limit": True}}, 100),
        ({"procs": {"history_limit": "7"}}, 100),
        ({"procs": []}, 100),
        ({"tasks": {"history_limit": 7}}, 7),
        ({"tasks": {"history_limit": 0}}, 100),
    ],
)
def test_proc_history_limit_validation(
    monkeypatch: Any, config: dict[str, Any], expected: int
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_proc_history_limit() == expected


def test_proc_history_limit_prefers_canonical_key_over_legacy(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {
            "procs": {"history_limit": 3},
            "tasks": {"history_limit": 9},
        },
    )

    assert config_core.get_proc_history_limit() == 3


def test_proc_history_limit_legacy_key_alone_still_works(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"tasks": {"history_limit": 9}},
    )

    assert config_core.get_proc_history_limit() == 9
    # The legacy accessor alias keeps working for callers not yet migrated.
    assert config_core.get_task_history_limit() == 9


def test_proc_history_config_default_and_schema() -> None:
    root = Path(__file__).parents[1]
    defaults = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert defaults["procs"]["history_limit"] == 100
    history = schema["properties"]["procs"]["properties"]["history_limit"]
    assert history["type"] == "integer"
    assert history["minimum"] == 1
    assert history["default"] == 100
    assert schema["properties"]["procs"]["additionalProperties"] is False
    assert schema["properties"]["tasks"]["deprecated"] is True


def test_filter_procs_applies_every_supported_filter() -> None:
    wanted = _proc("wanted-proc1", label="Compile Docs", command=["mkdocs", "build"])
    other = _proc(
        "other-proc22",
        status="error",
        label="Tests",
        project="other",
        session_id=None,
        tags=["ci"],
        command=["pytest"],
        cl_name="test_suite",
    )
    procs = [wanted, other]

    assert filter_procs(procs, status="pending") == [wanted]
    assert filter_procs(procs, status={"error"}) == [other]
    assert filter_procs(procs, session_id="session-a") == [wanted]
    assert filter_procs(procs, session_id=None) == [other]
    assert filter_procs(procs, project="other") == [other]
    assert filter_procs(procs, tag="docs") == [wanted]
    assert filter_procs(procs, query="MKDOCS BUILD") == [wanted]
    assert filter_procs(procs, query="test_suite") == [other]


def test_kind_filter_selects_one_or_many_proc_kinds(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    command = _proc("command-proc", created_at="2026-07-25T12:00:00Z")
    detached = _proc(
        "detach-proc1",
        kind=DETACHED_PROC_KIND,
        session_id=None,
        created_at="2026-07-25T12:01:00Z",
    )
    mirrored = _proc(
        "mirror-proc1", kind=TUI_PROC_KIND, created_at="2026-07-25T12:02:00Z"
    )
    for proc in (command, detached, mirrored):
        append_proc(proc, path=store, history_limit=10)

    assert read_procs(path=store, kind=DETACHED_PROC_KIND) == [detached]
    assert read_procs(path=store, kind={COMMAND_PROC_KIND, DETACHED_PROC_KIND}) == [
        detached,
        command,
    ]
    assert len(read_procs(path=store)) == 3
    assert filter_procs([command, detached, mirrored], kind=TUI_PROC_KIND) == [mirrored]


def test_rust_facade_round_trip_update_and_get(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    proc = _proc("0123456789ab")

    appended = append_proc(proc, path=store, history_limit=5)
    updated = update_proc(
        proc.proc_id,
        path=store,
        status="running",
        phase=None,
        pid=4321,
    )

    assert appended.schema_version == PROC_WIRE_SCHEMA_VERSION
    assert updated.matched is True
    assert updated.proc is not None
    assert updated.proc.status == "running"
    assert updated.proc.phase is None
    assert updated.proc.pid == 4321
    assert get_proc(proc.proc_id, path=store) == updated.proc
    assert read_procs(path=store, status="running") == [updated.proc]


def test_proc_shell_reserve_conflicts_and_lifecycle_facade(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"

    reserved = reserve_proc(_reserve("reserved-one"), path=store, history_limit=10)
    assert reserved.reserved is True
    assert reserved.replayed is False
    assert reserved.proc.schema_version == PROC_WIRE_SCHEMA_VERSION
    assert reserved.proc.lifecycle == "proc-shell"
    assert reserved.proc.argv == ["just", "docs"]

    replay = reserve_proc(
        _reserve("other-proc", fingerprint="fingerprint"),
        path=store,
        history_limit=10,
    )
    assert replay.reserved is False
    assert replay.replayed is True
    assert replay.proc.proc_id == "reserved-one"

    with pytest.raises(ValueError, match="shell_name"):
        reserve_proc(
            _reserve("conflict-one", fingerprint="different"),
            path=store,
            history_limit=10,
        )

    with pytest.raises(ValueError, match="concurrency_key"):
        reserve_proc(
            _reserve(
                "conflict-two",
                shell_name="agent--test",
                fingerprint="third",
                concurrency_keys=["docs"],
            ),
            path=store,
            history_limit=10,
        )

    with pytest.raises(ValueError, match="claimed"):
        finish_proc(
            ProcFinish(
                proc_id="reserved-one",
                supervisor_id="supervisor-a",
                status="success",
                finished_at="2026-07-25T12:00:10Z",
                exit_code=0,
            ),
            path=store,
        )

    claimed = claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            claimed_at="2026-07-25T12:00:01Z",
            pid=123,
            pgid=123,
        ),
        path=store,
    ).proc
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.supervisor_id == "supervisor-a"

    stopped = request_proc_stop(
        ProcStopRequest(
            proc_id="reserved-one",
            requested_by="agent-one",
            requested_at="2026-07-25T12:00:02Z",
            reason="user",
        ),
        path=store,
    ).proc
    assert stopped is not None
    assert stopped.status == "running"
    assert stopped.stop_requested_by == "agent-one"

    with pytest.raises(ValueError, match="transition"):
        update_proc(
            "reserved-one",
            path=store,
            status="success",
            finished_at="2026-07-25T12:00:10Z",
        )

    settling = begin_proc_settlement(
        ProcSettlement(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            settling_at="2026-07-25T12:00:03Z",
            exit_code=0,
            message="done",
        ),
        path=store,
    ).proc
    assert settling is not None
    assert settling.status == "settling"

    finished = finish_proc(
        ProcFinish(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            status="success",
            finished_at="2026-07-25T12:00:10Z",
            exit_code=0,
            message="done",
            result={"ok": True},
        ),
        path=store,
    ).proc
    assert finished is not None
    assert finished.status == "success"
    assert finished.finished_by == "supervisor-a"
    assert finished.result == {"ok": True}


def test_retention_and_pruning_delete_corresponding_logs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    store = tmp_path / "procs.jsonl"
    first = _proc(
        "first-proc01",
        status="success",
        created_at="2026-07-25T12:00:00Z",
    )
    second = _proc(
        "second-proc2",
        status="success",
        created_at="2026-07-25T12:01:00Z",
    )
    artifact_owned = _proc(
        "artifact-log",
        status="success",
        created_at="2026-07-25T12:00:30Z",
    )
    artifact_owned = Proc.from_dict(
        {**artifact_owned.to_dict(), "log_owner": "artifact"}
    )
    running = _proc(
        "running-proc",
        status="running",
        created_at="2026-07-25T11:00:00Z",
    )
    for proc in (first, artifact_owned, second, running):
        log = proc_log_path(proc.proc_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(proc.proc_id, encoding="utf-8")
        append_proc(proc, path=store, history_limit=10)

    outcome = prune_procs(path=store, history_limit=1)

    assert outcome.pruned_proc_ids == [first.proc_id, artifact_owned.proc_id]
    assert outcome.pruned_log_proc_ids == [first.proc_id]
    assert [proc.proc_id for proc in outcome.snapshot.procs] == [
        second.proc_id,
        running.proc_id,
    ]
    assert not proc_log_path(first.proc_id).exists()
    assert proc_log_path(artifact_owned.proc_id).exists()
    assert proc_log_path(second.proc_id).exists()
    assert proc_log_path(running.proc_id).exists()


def test_delete_proc_logs_skips_paths_outside_the_proc_log_root(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    outside = tmp_path / "artifacts" / "owned.log"
    outside.parent.mkdir(parents=True)
    outside.write_text("keep", encoding="utf-8")

    delete_proc_logs(["escape-proc"], log_paths={"escape-proc": str(outside)})

    assert outside.read_text(encoding="utf-8") == "keep"


def test_read_proc_log_tail_follows_an_explicit_log_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "out.log"
    custom.parent.mkdir(parents=True)
    custom.write_text("alpha\nbeta\n", encoding="utf-8")

    assert read_proc_log_tail("ignored-id", 1, log_path=custom) == "beta\n"
