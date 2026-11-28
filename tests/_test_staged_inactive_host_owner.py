"""Lane, pending-owner, and cleanup cases for inactive settlement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_questions_staged_record,
)
from tests._staged_inactive_host_helpers import (
    MONITOR_ID,
    OTHER_STAGED_ID,
    STAGED_ID,
    artifact_dir,
    patch_owner_home,
    write_held_receipt,
    write_member_launch,
    write_monitor_stage,
    write_origin_meta,
    write_owner_index,
)
from tests._stranded_collector_helpers import PROJECT


def _lane_monitor(member: Path):
    from sase.monitor.models import MonitorRecord

    return MonitorRecord(
        monitor_id=MONITOR_ID,
        member_agent_name="sase-1.2--mon",
        lane="sase-1.2",
        project_name=PROJECT,
        artifacts_dir=str(member),
        timestamp="20261022120000",
        command="just check",
        cwd=str(member),
        reason="verify",
        label="just check",
        start_status="STAGED",
        stop_status="STAGED",
        timeout_seconds=2700.0,
        tail_lines=200,
        monitor_state="staged",
    )


def test_later_turn_questions_use_fresh_artifacts_after_settlement(
    monkeypatch, tmp_path, capsys
) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )
    from sase.main.questions_command_handler import handle_questions_command
    from sase.monitor.store_lane import _blocks_lane_start

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    monkeypatch.setenv("SASE_AGENT", "1")
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    original = (origin / STAGED_HANDOFF_FILENAME).read_bytes()
    assert _settle_inactive_staged_handoff(str(origin)).settled is True
    assert occupying_handoff_names(str(origin)) == (STAGED_HANDOFF_FILENAME,)
    assert _blocks_lane_start(_lane_monitor(member)) is False

    later = artifact_dir(tmp_path, "sase-1.2--later")
    (later / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2--later", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(later))
    questions = json.dumps([{"question": "ship it?"}])
    with pytest.raises(SystemExit) as staged_exit:
        handle_questions_command(questions)
    assert staged_exit.value.code == 0
    later_record = json.loads(
        (later / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert later_record["kind"] == "questions"
    assert occupying_handoff_names(str(later)) == (STAGED_HANDOFF_FILENAME,)
    assert (origin / STAGED_HANDOFF_FILENAME).read_bytes() == original
    saved = json.loads((origin / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8"))
    assert saved["kind"] == "monitor"
    assert saved["staged_id"] == STAGED_ID
    output = capsys.readouterr().out
    assert output.startswith("Staged")

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(origin))
    with pytest.raises(SystemExit) as refused:
        handle_questions_command(questions)
    assert refused.value.code == 1
    assert (origin / STAGED_HANDOFF_FILENAME).read_bytes() == original


def test_live_origin_monitor_blocks_lane_and_holds_owner(monkeypatch, tmp_path) -> None:
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    assert _blocks_lane_start(_lane_monitor(member)) is True
    assert _pending_staged_monitor_owner(MONITOR_ID) is True


def test_failed_origin_releases_lane_and_pending_owner(monkeypatch, tmp_path) -> None:
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    assert _blocks_lane_start(_lane_monitor(member)) is False
    assert _pending_staged_monitor_owner(MONITOR_ID) is False


def test_settlement_removes_pending_owner_row_and_keeps_lane_clear(
    monkeypatch, tmp_path
) -> None:
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.cleanup_complete is True
    assert settlement.cleared_pending_owner is True
    assert read_staged_owner_index(MONITOR_ID) is None
    assert _pending_staged_monitor_owner(MONITOR_ID) is False
    # The lane record survives, but the frozen launch payload still proves
    # the stage is inactive, so the dead monitor keeps the lane clear.
    assert _blocks_lane_start(_lane_monitor(member)) is False


def test_incomplete_cleanup_stays_retryable(monkeypatch, tmp_path) -> None:
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    from sase.monitor.start_stage_cleanup import (
        cleanup_staged_monitor as real_cleanup,
    )

    calls: list[str] = []
    fail = True

    def _maybe_boom(artifacts_dir: str, **kwargs: Any) -> Any:
        calls.append(artifacts_dir)
        if fail:
            raise OSError("cleanup failed")
        return real_cleanup(artifacts_dir, **kwargs)

    monkeypatch.setattr(
        "sase.monitor.start_stage_cleanup.cleanup_staged_monitor", _maybe_boom
    )
    first = _settle_inactive_staged_handoff(str(origin))
    assert first.settled is False
    assert first.already_settled is False
    assert first.cleanup_complete is False
    assert "cleanup failed" in first.reason
    assert (origin / ".sase_handoff_settled_inactive.json").exists() is False
    assert read_staged_owner_index(MONITOR_ID) is not None
    assert (origin / STAGED_HANDOFF_FILENAME).is_file()
    assert calls == [str(member)]

    fail = False
    second = _settle_inactive_staged_handoff(str(origin))
    assert second.settled is True
    assert second.already_settled is False
    assert second.cleanup_complete is True
    assert read_staged_owner_index(MONITOR_ID) is None
    marker = json.loads(
        (origin / ".sase_handoff_settled_inactive.json").read_text(encoding="utf-8")
    )
    assert marker["staged_id"] == STAGED_ID


def test_premature_marker_does_not_skip_unfinished_cleanup(
    monkeypatch, tmp_path
) -> None:
    from sase.agent._staged_handoff_inactive import (
        INACTIVE_SETTLEMENT_SCHEMA_VERSION,
        write_inactive_settlement_locked,
    )
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    write_inactive_settlement_locked(
        {
            "schema_version": INACTIVE_SETTLEMENT_SCHEMA_VERSION,
            "staged_id": STAGED_ID,
            "reason": "origin_failed",
            "origin_id": "sase-1.2",
            "settled_at": "2026-10-28T12:02:00Z",
        },
        artifacts_dir=str(origin),
    )
    from sase.monitor.start_stage_cleanup import (
        cleanup_staged_monitor as real_cleanup,
    )

    calls: list[str] = []
    fail = True

    def _maybe_boom(artifacts_dir: str, **kwargs: Any) -> Any:
        calls.append(artifacts_dir)
        if fail:
            raise OSError("cleanup failed")
        return real_cleanup(artifacts_dir, **kwargs)

    monkeypatch.setattr(
        "sase.monitor.start_stage_cleanup.cleanup_staged_monitor", _maybe_boom
    )
    first = _settle_inactive_staged_handoff(str(origin))
    assert first.settled is False
    assert first.already_settled is False
    assert first.cleanup_complete is False
    assert read_staged_owner_index(MONITOR_ID) is not None
    assert calls == [str(member)]

    fail = False
    second = _settle_inactive_staged_handoff(str(origin))
    assert second.settled is True
    assert second.cleanup_complete is True
    assert read_staged_owner_index(MONITOR_ID) is None
    assert calls == [str(member), str(member)]


def test_running_member_cleanup_stays_incomplete(monkeypatch, tmp_path) -> None:
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    (member / "agent_meta.json").write_text(
        json.dumps({"monitor_id": MONITOR_ID, "monitor_state": "running"}),
        encoding="utf-8",
    )
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is False
    assert settlement.cleanup_complete is False
    assert "still running" in settlement.reason
    assert (origin / ".sase_handoff_settled_inactive.json").exists() is False
    assert read_staged_owner_index(MONITOR_ID) is not None


def test_unreadable_owner_index_blocks_settlement(monkeypatch, tmp_path) -> None:
    from sase.monitor.staged_owner import (
        STAGED_OWNER_DIRNAME,
        read_staged_owner_index,
    )
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    index_path = home / STAGED_OWNER_DIRNAME / f"{MONITOR_ID}.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{broken", encoding="utf-8")
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is False
    assert settlement.cleanup_complete is False
    assert "unreadable" in settlement.reason
    assert (origin / ".sase_handoff_settled_inactive.json").exists() is False
    assert index_path.is_file()
    assert read_staged_owner_index(MONITOR_ID) is None


def test_mismatched_owner_index_is_not_deleted(monkeypatch, tmp_path) -> None:
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin, member_artifacts_dir=str(member))
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    from sase.monitor.staged_owner import write_staged_owner_index

    write_staged_owner_index(
        MONITOR_ID,
        staged_id=OTHER_STAGED_ID,
        artifacts_dir=str(member),
        starter_artifacts_dir=str(origin),
    )
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.cleanup_complete is True
    assert settlement.cleared_pending_owner is False
    row = read_staged_owner_index(MONITOR_ID)
    assert row is not None
    assert row["staged_id"] == OTHER_STAGED_ID


def test_fresh_turn_stages_questions_after_settlement(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.agent.staged_handoff import write_staged_handoff
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    patch_owner_home(monkeypatch, home)
    monkeypatch.setenv("SASE_AGENT", "1")
    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    write_member_launch(member, origin)
    write_owner_index(member, origin)
    assert _settle_inactive_staged_handoff(str(origin)).settled is True
    fresh = artifact_dir(tmp_path, "sase-1.2--retry")
    staged = build_questions_staged_record(
        questions=[{"question": "ship it?"}],
        dirty_obligations_at_stage=[],
    )
    path = write_staged_handoff(staged, artifacts_dir=str(fresh))
    assert path.is_file()
    assert occupying_handoff_names(str(fresh)) == (STAGED_HANDOFF_FILENAME,)
