"""UX surfaces for update-skew auto-restart (phase sase-1j6.8).

Covers the RESTARTING status mapping in both done-wire loaders, the
decline/stale dim hints, the replacement provenance block and ``v`` file
hint, and the help/update-hint copy.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

from rich.text import Text

from sase.ace.tui.models._loaders._done_loaders import (
    _load_done_agent_for_dir,
    load_done_agents_from_snapshot,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent_prefix import (
    append_agent_row_prefix,
)
from sase.ace.tui.widgets._agent_list_render_agent_status import (
    append_agent_row_status,
)
from sase.agent.auto_restart.constants import UPDATE_RECOVERY_GLYPH
from sase.agent.auto_restart.ux import (
    _is_stale_pending,
    _recovery_is_in_flight,
    apply_provenance_to_agent,
    apply_recovery_to_agent,
    auto_restart_provenance_lines,
    declined_hint,
    restarting_hint,
)
from sase.core.agent_auto_restart_wire import AgentRecoveryWire
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    DoneMarkerWire,
)

PROVENANCE = {
    "of_artifacts_dir": "/artifacts/ace-run/20261009120000",
    "of_timestamp": "20261009120000",
    "lineage_root": "20261009120000",
    "episode_id": "sase@9fd8a08",
    "ledger_key": "sase__20261009120000",
    "evidence_dir": "/home/user/.sase/restarts/20261009-test",
    "signature": "ImportError · cannot import name 'auto_launch_prefix'",
    "from_rev": "9c5000f",
    "to_rev": "9fd8a08",
    "culprit_commit": "9fd8a081f4",
    "culprit_subject": "feat(autonomy): structural inheritance",
    "restarted_at": "2026-10-09T12:05:00+00:00",
}


def _agent(**overrides: object) -> Agent:
    fields: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "ux",
        "project_file": "/tmp/project.sase",
        "status": "FAILED",
        "start_time": datetime(2026, 10, 9, 12, 0, 0),
    }
    fields.update(overrides)
    return Agent(**fields)  # type: ignore[arg-type]


def test_recovery_is_in_flight_matches_healer_states() -> None:
    assert _recovery_is_in_flight("pending")
    assert _recovery_is_in_flight("deferred")
    assert _recovery_is_in_flight("launching")
    assert not _recovery_is_in_flight("declined")
    assert not _recovery_is_in_flight("launched")
    assert not _recovery_is_in_flight(None)
    assert _is_stale_pending("deferred", None, pending_resurface_seconds=600) is False


def test_restarting_hint_names_episode_for_pending() -> None:
    hint = restarting_hint("pending", episode_id="sase@9fd8a08")
    assert "restarting once the update settles" in hint
    assert "9fd8a08" in hint


def test_restarting_hint_for_deferred() -> None:
    assert restarting_hint("deferred") == (
        f"{UPDATE_RECOVERY_GLYPH} waiting for the sase update to finish"
    )


def test_declined_hint_prefers_writer_copy() -> None:
    assert (
        declined_hint(None, "auto-restart skipped — already restarted once")
        == "auto-restart skipped — already restarted once"
    )
    assert declined_hint(None, None) is None


def test_apply_recovery_promotes_in_flight() -> None:
    agent = _agent()
    assert (
        apply_recovery_to_agent(agent, state="launching", episode_id="sase@9fd8a08")
        == "RESTARTING"
    )
    assert agent.recovery_state == "launching"
    assert agent.recovery_episode_id == "sase@9fd8a08"
    assert agent.recovery_stale_pending is False


def test_apply_recovery_flags_stale_pending() -> None:
    agent = _agent()
    old = (datetime.now(UTC) - timedelta(seconds=3600)).isoformat()
    assert (
        apply_recovery_to_agent(
            agent,
            state="pending",
            requested_at=old,
            pending_resurface_seconds=600,
        )
        is None
    )
    assert agent.recovery_stale_pending is True
    assert agent.recovery_state == "pending"


def test_apply_recovery_keeps_declined_failed() -> None:
    agent = _agent()
    assert (
        apply_recovery_to_agent(
            agent,
            state="declined",
            reason_text="auto-restart skipped — already restarted once",
        )
        is None
    )
    assert agent.recovery_state == "declined"
    assert "already restarted once" in (agent.recovery_reason_text or "")


def test_apply_provenance_registers_evidence_directory_hint() -> None:
    agent = _agent(status="DONE")
    apply_provenance_to_agent(agent, PROVENANCE)
    assert agent.auto_restart_provenance is not None
    assert agent.auto_restart_provenance["ledger_key"] == "sase__20261009120000"
    assert "/home/user/.sase/restarts/20261009-test" in agent.extra_files


def test_provenance_lines_render_update_range() -> None:
    lines = auto_restart_provenance_lines(PROVENANCE)
    assert lines[0] == (
        f"{UPDATE_RECOVERY_GLYPH} Auto-restarted after sase update 9c5000f → 9fd8a08"
    )
    assert any("auto_launch_prefix" in line for line in lines)
    assert lines[-1] == "  broke before its model turn · nothing lost"


def _write_fs_row(artifact_dir: Path, *, recovery: dict[str, object] | None) -> None:
    artifact_dir.mkdir(parents=True)
    done: dict[str, object] = {
        "cl_name": "ux_row",
        "project_file": "/tmp/project.sase",
        "outcome": "failed",
        "error": "ImportError: cannot import name 'auto_launch_prefix'",
    }
    if recovery is not None:
        done["recovery"] = recovery
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def test_fs_loader_maps_pending_to_restarting(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20261009120000"
    _write_fs_row(
        artifact_dir,
        recovery={
            "state": "pending",
            "requested_at": datetime.now(UTC).isoformat(),
            "episode_id": "sase@9fd8a08",
        },
    )
    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
    assert agent is not None
    assert agent.status == "RESTARTING"
    assert agent.recovery_state == "pending"


def test_fs_loader_keeps_declined_failed_with_hint(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20261009120100"
    _write_fs_row(
        artifact_dir,
        recovery={
            "state": "declined",
            "reason_text": "auto-restart skipped — already restarted once",
        },
    )
    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
    assert agent is not None
    assert agent.status == "FAILED"
    assert agent.recovery_state == "declined"


def test_fs_loader_projects_meta_provenance(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20261009120200"
    _write_fs_row(artifact_dir, recovery=None)
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "ux_row",
                "project_file": "/tmp/project.sase",
                "outcome": "completed",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"auto_restart": PROVENANCE}), encoding="utf-8"
    )
    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
    assert agent is not None
    assert agent.auto_restart_provenance is not None
    assert "/home/user/.sase/restarts/20261009-test" in agent.extra_files


def _snapshot_record(
    artifact_dir: Path, recovery: AgentRecoveryWire | None
) -> AgentArtifactScanWire:
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(artifact_dir.parent.parent),
        project_file=str(artifact_dir.parent.parent / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp="20261009120300",
        done=DoneMarkerWire(
            outcome="failed",
            cl_name="ux_row",
            project_file="/tmp/project.sase",
            error="ImportError: cannot import name 'auto_launch_prefix'",
            recovery=recovery,
        ),
        has_done_marker=True,
    )
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(artifact_dir.parent.parent),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )


def test_snapshot_loader_maps_launching_to_restarting(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts" / "ace-run" / "20261009120300"
    artifact_dir.mkdir(parents=True)
    agents = load_done_agents_from_snapshot(
        _snapshot_record(
            artifact_dir,
            AgentRecoveryWire(state="launching", episode_id="sase@9fd8a08"),
        ),
        {},
        {},
    )
    assert len(agents) == 1
    assert agents[0].status == "RESTARTING"


def test_snapshot_loader_keeps_declined_failed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts" / "ace-run" / "20261009120400"
    artifact_dir.mkdir(parents=True)
    agents = load_done_agents_from_snapshot(
        _snapshot_record(
            artifact_dir,
            AgentRecoveryWire(
                state="declined",
                reason_text="auto-restart skipped — already restarted once",
            ),
        ),
        {},
        {},
    )
    assert len(agents) == 1
    assert agents[0].status == "FAILED"
    assert agents[0].recovery_state == "declined"


def test_restarting_row_renders_glyph_and_hint() -> None:
    agent = _agent(status="RESTARTING")
    agent.recovery_state = "pending"
    agent.recovery_episode_id = "sase@9fd8a08"
    text = Text()
    append_agent_row_status(text, agent)
    assert "↻ RESTARTING" in text.plain
    assert "restarting once the update settles" in text.plain


def test_failed_declined_row_renders_reason() -> None:
    agent = _agent()
    agent.recovery_state = "declined"
    agent.recovery_reason_text = "auto-restart skipped — already restarted once"
    text = Text()
    append_agent_row_status(text, agent)
    assert "FAILED" in text.plain
    assert "already restarted once" in text.plain


def test_replacement_row_carries_chip() -> None:
    agent = _agent(status="DONE")
    agent.auto_restart_provenance = dict(PROVENANCE)
    text = append_agent_row_prefix(agent, is_selected=False)
    assert "↻" in text.plain


def test_help_reference_covers_restarting() -> None:
    from sase.ace.tui.keymaps import KeymapRegistry
    from sase.ace.tui.modals.help_modal.agents_reference_sections import (
        reference_sections,
    )
    from tests._keymaps_helpers import default_app_keymaps

    sections = reference_sections(KeymapRegistry(app=default_app_keymaps()))
    hay = "\n".join(f"{title} {row}" for title, rows in sections for row in rows)
    assert "↻ RESTARTING" in hay
    assert "Auto-restart in flight" in hay


def test_update_hint_hidden_without_holders() -> None:
    from sase.main.update_render import _auto_restart_hint_line

    assert _auto_restart_hint_line() is None
