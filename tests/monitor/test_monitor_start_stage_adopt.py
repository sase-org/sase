"""Checkpoint freeze, adoption, persist, replay, and workspace pinning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import read_staged_handoff
from sase.core.staged_handoff import staged_monitor_launch_payload_schema_version
from sase.monitor.models import MonitorAlreadyRunningError, MonitorError
from sase.monitor.start import start_monitor
from sase.monitor.start_stage import (
    launch_from_persisted_payload,
    stage_monitor,
)
from sase.monitor.start_stage_adopt import _load_staged_monitor_launch_payload
from sase.monitor.staged_owner import launch_payload_path
from tests.monitor._fixtures import (
    record_from_disk,
    register_workspace_checkout,
    wait_for_done,
)

from ._start_stage import (
    sandbox_home as sandbox_home,
    sandbox_project,
    stage_env,
    stage_request,
)

__all__ = [
    "test_nested_cwd_and_explicit_lane_freeze_workspace",
    "test_stage_blocks_lane_and_replays_identical_request",
    "test_stage_persists_payload_and_reconstructs",
    "test_staged_authored_checkpoint_missing_or_corrupt_refuses_before_launch",
    "test_staged_authored_checkpoint_survives_cli_file_removal",
    "test_staged_monitor_adoption_saves_real_response_and_exact_starter_parent",
    "test_staged_monitor_rejects_foreign_persisted_starter_before_launch",
    "test_tool_run_id_is_stable_from_stage_to_launch",
]


def test_staged_authored_checkpoint_survives_cli_file_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.continuation_capture import load_authored_checkpoint

    dirs = stage_env(tmp_path, monkeypatch)
    source = tmp_path / "authored-checkpoint.yml"
    source.write_text(
        "objective: verify the staged change\nconstraints:\n  - keep the workspace\n",
        encoding="utf-8",
    )
    authored = load_authored_checkpoint(source)
    staged = stage_monitor(
        stage_request(
            tmp_path,
            checkpoint_ref=authored.content_ref,
            checkpoint_document=authored.payload,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    source.write_text("objective: changed after staging\n", encoding="utf-8")
    source.unlink()

    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    claim = payload["workspace"]["claim_context"]
    frozen_ref = claim["checkpoint_content_ref"]
    frozen_path = Path(staged.record.artifacts_dir) / frozen_ref.removeprefix("local:")
    assert frozen_path.is_file()
    assert claim["checkpoint_content_required"] is True

    captured: dict[str, Any] = {}

    def fake_launch(context: Any, timer: Any) -> Any:
        del timer
        captured["request"] = context.request
        return staged.record

    monkeypatch.setattr("sase.monitor.start_stage_adopt.launch_monitor", fake_launch)
    launched = launch_from_persisted_payload(staged.record.artifacts_dir)

    assert launched.monitor_id == staged.record.monitor_id
    assert captured["request"].checkpoint_ref == authored.content_ref
    assert captured["request"].checkpoint_document == authored.payload


@pytest.mark.parametrize("damage", ["remove", "corrupt"])
def test_staged_authored_checkpoint_missing_or_corrupt_refuses_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    from sase.continuation_capture import load_authored_checkpoint

    dirs = stage_env(tmp_path, monkeypatch)
    source = tmp_path / "authored-checkpoint.yml"
    source.write_text("objective: preserve the stage\n", encoding="utf-8")
    authored = load_authored_checkpoint(source)
    staged = stage_monitor(
        stage_request(
            tmp_path,
            checkpoint_ref=authored.content_ref,
            checkpoint_document=authored.payload,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    frozen_ref = payload["workspace"]["claim_context"]["checkpoint_content_ref"]
    frozen_path = Path(staged.record.artifacts_dir) / frozen_ref.removeprefix("local:")
    if damage == "remove":
        frozen_path.unlink()
    else:
        frozen_path.write_text("{broken json", encoding="utf-8")

    launched: list[bool] = []
    monkeypatch.setattr(
        "sase.monitor.start_stage_adopt.launch_monitor",
        lambda *_args, **_kwargs: launched.append(True),
    )
    with pytest.raises(MonitorError, match="staged authored checkpoint"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    assert launched == []


@pytest.mark.parametrize(
    ("starter_name", "agent_session", "expected_starter"),
    [
        ("acme", None, "acme--0"),
        ("acme--1", "acme", "acme--1"),
    ],
)
def test_staged_monitor_adoption_saves_real_response_and_exact_starter_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    starter_name: str,
    agent_session: str | None,
    expected_starter: str,
) -> None:
    from dataclasses import replace

    from sase.agent.staged_handoff import (
        read_staged_handoff,
        write_staged_handoff_response,
    )
    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_finalize import finalize_loop
    from sase.axe.run_agent_exec_retry import RetryTracker
    from sase.axe.run_agent_exec_staged import (
        STAGED_HANDOFF_ADOPTERS,
        StagedInlineContinuation,
    )
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    dirs = stage_env(
        tmp_path,
        monkeypatch,
        starter_name=starter_name,
        agent_session=agent_session,
    )
    starter_dir = Path(dirs[0])
    original_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    staged = stage_monitor(stage_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    handoff = read_staged_handoff(starter_dir)
    assert handoff is not None
    write_staged_handoff_response(
        str(handoff["staged_id"]),
        "The provider's real final response.",
        artifacts_dir=str(starter_dir),
    )

    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(starter_dir),
        agent_name=starter_name,
        agent_meta=original_meta,
        project_name="proj",
    )
    state = LoopState(
        current_prompt="Run the staged verification.",
        current_role_suffix="",
        current_artifacts_dir=str(starter_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run the staged verification.",
    )
    captured: dict[str, Any] = {}

    def fake_launch(context: Any, timer: Any) -> Any:
        del timer
        captured["context"] = context
        assert not (starter_dir / "done.json").exists()
        return staged.record

    monkeypatch.setattr("sase.monitor.start_stage_adopt.launch_monitor", fake_launch)
    outcome = STAGED_HANDOFF_ADOPTERS["monitor"](
        handoff,
        json.loads((starter_dir / "agent_meta.json").read_text()),
        StagedInlineContinuation(ctx=ctx, state=state),
        "The provider's real final response.",
    )
    assert outcome.outcome == "monitored"

    starter_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    assert starter_meta["name"] == expected_starter
    assert state.saved_chat_paths
    chat_path = Path(state.saved_chat_paths[-1][1])
    chat = chat_path.read_text(encoding="utf-8")
    assert "The provider's real final response." in chat
    assert "# Monitor handoff" in chat
    assert "verify staging" in chat
    assert starter_meta["chat_path"] == str(chat_path)

    delta_files = list(
        (starter_dir / "continuation" / "records" / "agent_delta").glob("*.json")
    )
    assert len(delta_files) == 1
    delta = json.loads(delta_files[0].read_text(encoding="utf-8"))
    assert delta["status"] == "completed"
    assert delta["final_response_ref"]
    assert delta["handoff_checkpoint_ref"]

    monitor_context = captured["context"]
    starter_node_id = starter_meta["continuation_node_id"]
    assert monitor_context.request.parent_node_ids == (starter_node_id,)
    member_meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert member_meta["continuation_parent_node_ids"] == [starter_node_id]
    assert member_meta["monitor_starter_agent"] == expected_starter

    state.loop_outcome = "monitored"
    result = finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)
    done = json.loads((starter_dir / "done.json").read_text(encoding="utf-8"))
    assert result.outcome == "monitored"
    assert done["response_path"] == str(chat_path)
    assert done["continuation"]["node_id"] == starter_node_id


def test_staged_monitor_rejects_foreign_persisted_starter_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from sase.agent.staged_handoff import StagedHandoffError
    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_staged import (
        STAGED_HANDOFF_ADOPTERS,
        StagedInlineContinuation,
    )
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    dirs = stage_env(tmp_path, monkeypatch)
    starter_dir = Path(dirs[0])
    original_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    staged = stage_monitor(stage_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    handoff = read_staged_handoff(starter_dir)
    assert handoff is not None

    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(starter_dir),
        agent_name="acme",
        agent_meta=original_meta,
        project_name="proj",
    )
    state = LoopState(
        current_prompt="Run the staged verification.",
        current_role_suffix="",
        current_artifacts_dir=str(starter_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run the staged verification.",
    )
    foreign_metadata = json.loads((starter_dir / "agent_meta.json").read_text())
    foreign_metadata["name"] = "outsider--0"
    launches: list[bool] = []
    monkeypatch.setattr(
        "sase.monitor.start_stage.launch_from_persisted_payload",
        lambda *_args, **_kwargs: launches.append(True),
    )

    with pytest.raises(StagedHandoffError, match="persisted agent identity"):
        STAGED_HANDOFF_ADOPTERS["monitor"](
            handoff,
            foreign_metadata,
            StagedInlineContinuation(ctx=ctx, state=state),
            "The provider's real final response.",
        )

    assert launches == []
    member_meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert member_meta["monitor_state"] == "staged"


def test_stage_persists_payload_and_reconstructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    assert staged.replayed is False
    assert staged.record.monitor_state == "staged"
    assert staged.record.pid is None
    payload_path = launch_payload_path(staged.record.artifacts_dir)
    assert payload_path.is_file()
    loaded = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert loaded["schema_version"] == staged_monitor_launch_payload_schema_version()
    assert loaded["staged_id"] == staged.staged_id
    assert loaded["monitor_id"] == staged.record.monitor_id
    assert loaded["cwd"] == str(tmp_path)
    assert loaded["workspace"]["mode"] == "inherit"
    disk = record_from_disk(staged.record.artifacts_dir)
    assert disk.agent_meta is not None
    assert disk.agent_meta.agent_session_turn is not None
    assert disk.agent_meta.agent_session_turn.state == "staged"
    handoff = read_staged_handoff(dirs[0])
    assert handoff is not None
    assert handoff["kind"] == "monitor"
    assert handoff["staged_id"] == staged.staged_id
    assert handoff["successor_workspace"] == "inherit"
    assert handoff["carry_allowed"] is True


def test_stage_blocks_lane_and_replays_identical_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    first = stage_monitor(stage_request(tmp_path, command="sleep 30"))
    dirs.append(first.record.artifacts_dir)

    with pytest.raises(MonitorAlreadyRunningError):
        stage_monitor(stage_request(tmp_path, command="true"))
    with pytest.raises(MonitorAlreadyRunningError):
        start_monitor(stage_request(tmp_path, command="true"))

    replayed = stage_monitor(stage_request(tmp_path, command="sleep 30"))
    assert replayed.replayed is True
    assert replayed.record.monitor_id == first.record.monitor_id
    assert replayed.staged_id == first.staged_id


def test_nested_cwd_and_explicit_lane_freeze_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    nested = Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "sase-core"
    nested.mkdir(parents=True)
    dirs = stage_env(
        tmp_path,
        monkeypatch,
        cwd=str(nested),
        workspace_num=10,
        workspace_dir=str(primary),
        starter_workspace_dir=workspace_dir,
    )
    staged = stage_monitor(stage_request(tmp_path, cwd=str(nested)))
    dirs.append(staged.record.artifacts_dir)
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    claim = payload["workspace"]["claim_context"]
    assert payload["cwd"] == str(nested)
    assert payload["lane"] == "acme"
    assert int(claim["workspace_num"]) == 10


def test_tool_run_id_is_stable_from_stage_to_launch(
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
    assert run_id
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert payload["resources"]["tool_run_id"] == run_id
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.tool_run_id == run_id
        assert record.monitor_state == "running"
        assert record.monitor_id == staged.record.monitor_id
    finally:
        wait_for_done(record.artifacts_dir, timeout=30.0)
