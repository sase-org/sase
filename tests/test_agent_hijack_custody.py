"""Custody exemptions so every release path respects an active hijack."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.ace.tui.actions.agents._kill_persistence import _persist_running_kill
from sase.agent.hijack.custody import (
    ACTIVE_CUSTODY_STATES,
    _set_done_recovery_state,
    expire_hijack_hold,
    format_diff_summary,
    hijack_retains_claim,
    hijack_skips_claim_release,
    hijacked_at_exceeds_ttl,
    matching_active_record,
    recovery_is_user_parked,
)
from sase.agent.names._common import NamedAgent
from sase.agent.running import list_all_agents, list_running_agents
from sase.agents import cli_list, cli_show
from sase.bead import stranded_facts as stranded
from sase.core.agent_auto_restart_wire import AgentRecoveryWire
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.running_field import ClaimResult, WorkspaceClaim
from tests._agent_dismiss_helpers import make_agent
from tests._running_agents_snapshot_helpers import synthetic_snapshot
from tests._stranded_collector_helpers import record as stranded_record


def _claim(
    *,
    workspace_num: int = 4,
    pid: int = 123,
    pinned: bool = True,
    artifacts_timestamp: str = "20260901120000",
) -> WorkspaceClaim:
    return WorkspaceClaim(
        workspace_num=workspace_num,
        workflow="run",
        cl_name="feature",
        pid=pid,
        artifacts_timestamp=artifacts_timestamp,
        pinned=pinned,
    )


def _held_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "hijack_id": "h-1",
        "state": "held",
        "project_file": "/tmp/projects/proj/proj.sase",
        "workspace_num": 4,
        "pid": 123,
        "expected_claim_owner_pid": 123,
        "artifacts_dir": "/tmp/artifacts/h-1",
        "workspace_dir": "/tmp/ws-4",
        "agent_name": "held-agent",
        "hijacked_at": "2026-09-20T12:00:00",
        "snapshots": [],
        "repo_diffs": [],
    }
    record.update(overrides)
    return record


def test_matching_active_record_requires_project_workspace_and_pid() -> None:
    claim = _claim()
    record = _held_record()
    with patch(
        "sase.agent.hijack.custody.list_active_records",
        return_value=[record],
    ):
        assert matching_active_record("/tmp/projects/proj/proj.sase", claim) is record
        assert matching_active_record("/tmp/other.sase", claim) is None
        assert (
            matching_active_record("/tmp/projects/proj/proj.sase", _claim(pid=999))
            is None
        )


def test_successor_pid_does_not_retain_the_origin_claim() -> None:
    with patch(
        "sase.agent.hijack.custody.list_active_records",
        return_value=[_held_record()],
    ):
        assert (
            hijack_retains_claim("/tmp/projects/proj/proj.sase", _claim(pid=999))
            is False
        )


def test_ttl_is_measured_from_hijacked_at_not_launch_stamp() -> None:
    now = datetime(2026, 9, 20, 12, 0, 0)
    today = now.isoformat()
    thirteen = (now - timedelta(days=13)).isoformat()
    fifteen = (now - timedelta(days=15)).isoformat()
    assert hijacked_at_exceeds_ttl(today, 14, now=now) is False
    assert hijacked_at_exceeds_ttl(thirteen, 14, now=now) is False
    assert hijacked_at_exceeds_ttl(fifteen, 14, now=now) is True
    assert hijacked_at_exceeds_ttl(fifteen, 0, now=now) is False
    assert hijacked_at_exceeds_ttl(None, 14, now=now) is False


def test_cleanup_retains_requested_hijack_without_done_json() -> None:
    project_file = "/tmp/projects/proj/proj.sase"
    claim = _claim(pinned=False)
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep._matching_hijack_record",
            return_value=_held_record(state="requested"),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
        patch("sase.agent.hijack.custody.expire_hijack_hold") as expire,
    ):
        released = cleanup_stale_running_entries()
    assert released == 0
    release.assert_not_called()
    expire.assert_not_called()


def test_cleanup_retains_held_claim_younger_than_hijacked_at_ttl() -> None:
    project_file = "/tmp/projects/proj/proj.sase"
    now = datetime(2026, 9, 20, 12, 0, 0)
    claim = _claim(artifacts_timestamp="20260901120000")
    record = _held_record(hijacked_at=now.isoformat())
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep._matching_hijack_record",
            return_value=record,
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep._held_claim_ttl_days",
            return_value=14,
        ),
        patch("sase.agent.hijack.custody.hijacked_at_exceeds_ttl", return_value=False),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
        patch("sase.agent.hijack.custody.expire_hijack_hold") as expire,
    ):
        released = cleanup_stale_running_entries()
    assert released == 0
    release.assert_not_called()
    expire.assert_not_called()


def test_cleanup_expire_snapshot_failure_keeps_the_hold() -> None:
    project_file = "/tmp/projects/proj/proj.sase"
    claim = _claim()
    record = _held_record(hijacked_at="2026-08-01T12:00:00")
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep._matching_hijack_record",
            return_value=record,
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep._held_claim_ttl_days",
            return_value=14,
        ),
        patch("sase.agent.hijack.custody.hijacked_at_exceeds_ttl", return_value=True),
        patch("sase.agent.hijack.custody.expire_hijack_hold", return_value=False),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries()
    assert released == 0
    release.assert_not_called()


def test_expire_hijack_hold_keeps_claim_when_snapshot_fails() -> None:
    record = _held_record()
    with (
        patch(
            "sase.agent.hijack.custody._ensure_expiry_snapshots",
            return_value=([], "workspace fingerprint drifted"),
        ),
        patch("sase.agent.hijack.custody.cas_advance_record") as cas,
        patch("sase.running_field.release_workspace") as release,
    ):
        assert (
            expire_hijack_hold("/tmp/projects/proj/proj.sase", _claim(), record)
            is False
        )
    cas.assert_not_called()
    release.assert_not_called()


def test_expire_hijack_hold_cas_then_marks_done_and_releases(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "done.json").write_text(
        json.dumps(
            {
                "outcome": "hijacked",
                "recovery": {"kind": "hijack", "state": "pending"},
            }
        ),
        encoding="utf-8",
    )
    record = _held_record(artifacts_dir=str(artifacts), snapshots=[])
    expired = {**record, "state": "expired"}
    with (
        patch(
            "sase.agent.hijack.custody._ensure_expiry_snapshots",
            return_value=([], None),
        ),
        patch(
            "sase.agent.hijack.custody.cas_advance_record",
            return_value=expired,
        ) as cas,
        patch(
            "sase.running_field.release_workspace",
            return_value=ClaimResult(success=True),
        ) as release,
    ):
        assert (
            expire_hijack_hold("/tmp/projects/proj/proj.sase", _claim(), record) is True
        )
    cas.assert_called_once()
    release.assert_called_once()
    payload = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == "hijacked"
    assert payload["recovery"]["state"] == "expired"


def test_kill_persistence_skips_claim_release_for_active_hijack() -> None:
    agent = make_agent(
        workspace_num=4,
        artifacts_dir="/tmp/artifacts/h-1",
        project_file="/tmp/projects/proj/proj.sase",
    )
    with (
        patch(
            "sase.agent.hijack.custody.hijack_skips_claim_release",
            return_value=True,
        ),
        patch("sase.running_field.release_workspace") as release,
    ):
        _persist_running_kill(agent)
    release.assert_not_called()


def test_hijack_skips_claim_release_for_active_states() -> None:
    for state in ACTIVE_CUSTODY_STATES:
        with patch(
            "sase.agent.hijack.custody.load_record_by_artifacts_dir",
            return_value={"state": state},
        ):
            assert hijack_skips_claim_release(artifacts_dir="/tmp/a") is True
    with patch(
        "sase.agent.hijack.custody.load_record_by_artifacts_dir",
        return_value={"state": "expired"},
    ):
        assert hijack_skips_claim_release(artifacts_dir="/tmp/a") is False


def test_set_done_recovery_state_rewrites_only_recovery(tmp_path: Path) -> None:
    path = tmp_path / "done.json"
    path.write_text(
        json.dumps(
            {"outcome": "hijacked", "recovery": {"kind": "hijack", "state": "pending"}}
        ),
        encoding="utf-8",
    )
    _set_done_recovery_state(str(tmp_path), "expired")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["outcome"] == "hijacked"
    assert payload["recovery"]["state"] == "expired"
    assert payload["recovery"]["kind"] == "hijack"


def test_stranded_hijacked_owner_is_parked_by_user(tmp_path: Path) -> None:
    rec = stranded_record(
        tmp_path / "20261103120000",
        name="held-agent",
        session=None,
        done=DoneMarkerWire(
            outcome="hijacked",
            recovery=AgentRecoveryWire(state="pending", kind="hijack"),
        ),
    )
    assert stranded._lifecycle(rec) == "asking"
    assert stranded._process_live(rec) is True
    assert recovery_is_user_parked(AgentRecoveryWire(state="expired", kind="hijack"))
    assert not recovery_is_user_parked(
        AgentRecoveryWire(state="dismissed", kind="hijack")
    )


def test_format_diff_summary_compacts_repo_diffs() -> None:
    record = _held_record(
        repo_diffs=[
            {"files_changed": 2, "insertions": 10, "deletions": 3},
            {"files_changed": 1, "insertions": 2, "deletions": 1},
        ]
    )
    assert format_diff_summary(record) == "3 files +12 −4"


def test_list_running_agents_includes_hijacked_without_all(tmp_path: Path) -> None:
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path / "proj"),
        project_file=str(tmp_path / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(
            tmp_path / "proj" / "artifacts" / "ace-run" / "20261103120000"
        ),
        timestamp="20261103120000",
        agent_meta=AgentMetaWire(name="held-agent", pid=9),
        done=DoneMarkerWire(
            outcome="hijacked",
            name="held-agent",
            workspace_num=4,
            recovery=AgentRecoveryWire(state="pending", kind="hijack"),
        ),
        has_done_marker=True,
    )
    snapshot = synthetic_snapshot(tmp_path, [record])
    with (
        patch(
            "sase.agent.running_listing.listing_snapshot",
            return_value=(snapshot, None),
        ),
        patch(
            "sase.agent.hijack.core.agent_hijack_status_for_done_marker",
            return_value="HIJACKED",
        ),
    ):
        running = list_running_agents()
        all_agents = list_all_agents()
    assert [info.name for info in running] == ["held-agent"]
    assert running[0].status == "HIJACKED"
    assert [info.name for info in all_agents] == ["held-agent"]


def test_workspace_cell_shows_dim_held_hint() -> None:
    agent = SimpleNamespace(
        status="HIJACKED",
        workspace_num=4,
        artifacts_dir="/tmp/a",
    )
    with patch(
        "sase.agent.hijack.custody.hijack_skips_claim_release",
        return_value=True,
    ):
        cell = cli_list._workspace_cell(agent)
    assert str(cell) == "#4 held"


def test_agent_show_renders_hijack_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text("{}", encoding="utf-8")
    (artifacts_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "hijacked",
                "recovery": {"state": "pending", "kind": "hijack", "hijack_id": "h-1"},
            }
        ),
        encoding="utf-8",
    )
    agent = NamedAgent(
        name="held-agent",
        artifacts_dir=str(artifacts_dir),
        is_done=True,
        outcome="hijacked",
    )
    monkeypatch.setattr(cli_show, "find_named_agent", lambda _name: agent)
    monkeypatch.setenv("COLUMNS", "200")
    with (
        patch(
            "sase.agent.hijack.core.agent_hijack_status_for_done_marker",
            return_value="HIJACKED",
        ),
        patch(
            "sase.agent.hijack.custody.record_for_agent",
            return_value=_held_record(
                artifacts_dir=str(artifacts_dir),
                repo_diffs=[{"files_changed": 1, "insertions": 2, "deletions": 0}],
                snapshots=[{"repo": "/tmp/ws", "reference": "snap-1"}],
            ),
        ),
    ):
        cli_show.handle_agents_show(argparse.Namespace(name="held-agent"))
    out = capsys.readouterr().out
    assert "HIJACKED" in out
    assert "Hijack" in out
    assert "held" in out
    assert "snap-1" in out
    assert "1 files +2" in out
