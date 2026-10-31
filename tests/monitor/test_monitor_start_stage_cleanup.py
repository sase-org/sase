"""Held cleanup, join consume, ack rollback, and launch from persisted payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff
from sase.core.tool_run import tool_run_show
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.monitor.models import MonitorError
from sase.monitor.start import start_monitor
from sase.monitor.start_stage import (
    cleanup_staged_monitor,
    launch_from_persisted_payload,
    stage_monitor,
)
from sase.procs.submission import ProcSubmitError
from sase.tool.owner import observe_owner_fact
from tests.monitor._fixtures import wait_for_done
from tests.monitor._join_helpers import reserve_detached_run

from ._start_stage import (
    SANDBOX_CATALOG,
    read_reservations,
    sandbox_home as sandbox_home,
    sandbox_project,
    sealed_intent,
    stage_env,
    stage_request,
)

__all__ = [
    "test_ack_failure_rolls_back_staged_launch",
    "test_cleanup_at_resource_boundaries",
    "test_cleanup_releases_staged_join_without_stopping_run",
    "test_failed_finalization_releases_monitor_resources_and_keeps_stage",
    "test_held_cleanup_keeps_outer_record",
    "test_immediate_start_still_launches",
    "test_launch_from_persisted_payload_runs",
    "test_launcher_exit_keeps_pending_owner",
    "test_reserved_join_that_settles_before_adoption_is_consumed",
]


@pytest.mark.parametrize("resource", ["owned", "joined", "prepared"])
def test_failed_finalization_releases_monitor_resources_and_keeps_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    from unittest.mock import Mock

    from sase.axe.run_agent_exec_staged import (
        StagedInlineContinuation,
        dispatch_completed_staged_handoff,
    )
    from sase.monitor.staged_owner import read_staged_owner_index
    from tests.staged_handoff_acceptance_helpers import make_continuation

    root = sandbox_project(tmp_path)
    if resource == "prepared":
        (root / "sase" / "sase.yml").write_text(
            SANDBOX_CATALOG.replace('["true"]', '["just", "check"]'),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    joined_run = (
        reserve_detached_run("--", "true", agent="acme")
        if resource == "joined"
        else None
    )
    prepared = (
        persist_prepared_completion(
            sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
        )
        if resource == "prepared"
        else None
    )
    staged = stage_monitor(
        stage_request(
            tmp_path,
            cwd=str(root),
            command="just check" if prepared else "true",
            join_run_id=joined_run,
            profile="verify" if resource != "joined" else None,
            completion_ref=prepared.intent_ref if prepared else None,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    starter = Path(dirs[0])
    before = read_staged_handoff(dirs[0])
    (starter / "finalizer_result.json").write_text(
        json.dumps({"status": "failed", "instances": []}), encoding="utf-8"
    )
    submit = Mock(side_effect=AssertionError("held monitor must not launch"))
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", submit)
    continuation = StagedInlineContinuation(*make_continuation(tmp_path, starter))

    result = dispatch_completed_staged_handoff(dirs[0], continuation)

    assert result is not None and not result.adopted
    submit.assert_not_called()
    assert read_staged_handoff(dirs[0]) == before
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta.get("monitor_stage_held") is True
    assert read_staged_owner_index(staged.record.monitor_id) is None
    shown = tool_run_show(staged.record.tool_run_id)["run"]
    if resource == "joined":
        assert shown["state"] == "created"
        assert "staged_join_reservation" not in shown
        assert "join" not in shown
    else:
        assert shown["state"] != "created"
        assert shown.get("proc") is None
    if prepared:
        assert read_reservations(dirs[0]) == {}
        assert (
            load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])[
                "status"
            ]
            == "prepared"
        )

    # Repeated failure processing must retain the recovery evidence too.
    again = dispatch_completed_staged_handoff(dirs[0], continuation)
    assert again is not None and not again.adopted
    assert read_staged_handoff(dirs[0]) == before


@pytest.mark.parametrize(
    ("starter_name", "agent_session", "expected_starter"),
    [
        ("acme", None, "acme--0"),
        ("acme--1", "acme", "acme--1"),
    ],
)
def test_reserved_join_that_settles_before_adoption_is_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    starter_name: str,
    agent_session: str | None,
    expected_starter: str,
) -> None:
    from tests.monitor._join_helpers import settle_detached_run

    dirs = stage_env(
        tmp_path,
        monkeypatch,
        starter_name=starter_name,
        agent_session=agent_session,
    )
    run_id = reserve_detached_run("--", "true", agent=starter_name)
    staged = stage_monitor(stage_request(tmp_path, join_run_id=run_id))
    dirs.append(staged.record.artifacts_dir)
    starter_meta = json.loads((Path(dirs[0]) / "agent_meta.json").read_text())
    assert starter_meta["name"] == expected_starter
    settle_detached_run(
        run_id,
        state="succeeded",
        exit_code=0,
        terminal_cause="exited",
    )

    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert tool_run_show(run_id)["run"]["join"]["id"] == record.monitor_id
    assert record.tool_run_id == run_id
    done = wait_for_done(record.artifacts_dir, timeout=30.0)
    assert done["monitor_state"] == "completed"


def test_launcher_exit_keeps_pending_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.liveness import reconcile_unsettled_tool_runs

    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        stage_request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    assert run_id
    shown = tool_run_show(run_id)["run"]
    fact = observe_owner_fact(shown)
    assert fact is not None
    assert fact["state"] == "pending"
    reconcile_unsettled_tool_runs()
    after = tool_run_show(run_id)["run"]
    assert after["state"] == "created"
    assert after.get("terminal_cause") != "launch_failed"
    cleanup_staged_monitor(staged.record.artifacts_dir)


def test_ack_failure_rolls_back_staged_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    def _fail_submit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ProcSubmitError("ack failed")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fail_submit)
    with pytest.raises(MonitorError, match="ack failed"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "failed"
    assert meta.get("monitor_stage_held") is True
    assert read_staged_handoff(dirs[0]) is not None
    assert (Path(staged.record.artifacts_dir) / "done.json").is_file()


def test_cleanup_at_resource_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    bare = stage_monitor(stage_request(tmp_path, command="true"))
    dirs.append(bare.record.artifacts_dir)
    starter = dirs[0]
    result = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert result.held is False
    assert result.member_state == "failed"
    assert result.settled_tool_run_id is None
    assert not (Path(starter) / STAGED_HANDOFF_FILENAME).exists()
    again = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert again.member_state in {"failed", "staged"}


def test_cleanup_releases_staged_join_without_stopping_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    run_id = reserve_detached_run("--", "true", agent="acme")
    staged = stage_monitor(stage_request(tmp_path, join_run_id=run_id))
    dirs.append(staged.record.artifacts_dir)
    assert staged.record.tool_run_id == run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir)
    assert result.released_join is True
    assert result.settled_tool_run_id is None
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "created"


def test_held_cleanup_keeps_outer_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        stage_request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir, held=True)
    assert result.held is True
    assert result.settled_tool_run_id == run_id
    assert (Path(dirs[0]) / STAGED_HANDOFF_FILENAME).is_file()
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "staged"
    assert meta.get("monitor_stage_held") is True
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] != "created"
    with pytest.raises(MonitorError, match="canceled run"):
        launch_from_persisted_payload(staged.record.artifacts_dir)


def test_launch_from_persisted_payload_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.monitor_state == "running"
        assert record.pid is not None
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise


def test_immediate_start_still_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_env(tmp_path, monkeypatch)
    record = start_monitor(stage_request(tmp_path))
    try:
        assert record.monitor_state == "running"
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise
