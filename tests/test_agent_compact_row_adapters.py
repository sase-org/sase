"""Parity tests: compact row constructors vs full snapshot loaders.

Each scenario writes real marker JSON into a scratch artifact directory,
builds the oracle row through the real filesystem scan plus the existing
full snapshot loaders, and builds the candidate row from a hand-written
compact payload (shaped like the ``sase-core`` projection output for the
same logical record) through the new compact constructors. Every
list/filter/action fact must match; only explicitly deferred detail
fields may differ.

The guard tests fail the run if the compact path ever touches the
full-record Python decoder or the full snapshot constructors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.models._loaders._compact_done_loaders import (
    _build_done_agent_from_compact_record,
    load_done_agents_from_compact_snapshot,
)
from sase.ace.tui.models._loaders._compact_running_loaders import (
    _load_running_home_agents_from_compact_records,
    load_running_home_agents_from_compact_snapshot,
    _resolve_compact_running_home_records,
)
from sase.ace.tui.models._loaders._done_snapshot_loaders import (
    build_done_agent_from_record,
    load_done_agents_from_snapshot,
)
from sase.ace.tui.models._loaders._running_loaders import (
    load_running_home_agents_from_snapshot,
)
from tests._agent_compact_parity_helpers import DEFERRED_ATTRS
from tests._agent_compact_parity_helpers import _assert_parity
from tests._agent_compact_parity_helpers import _facts
from sase.core.agent_scan_facade import scan_agent_artifact_dirs
from sase.core.agent_scan_list_conversion import (
    _records_from_dicts as agent_artifact_list_records_from_dicts,
    agent_artifact_list_scan_wire_from_dict,
)


def _write_markers(artifact_dir: Path, markers: dict[str, Any]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in markers.items():
        (artifact_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _layout(tmp_path: Path, project: str, workflow: str, ts: str) -> tuple[Path, Path]:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / project / "artifacts" / workflow / ts
    return projects_root, artifact_dir


def _scan_full(projects_root: Path, artifact_dir: Path):
    snapshot = scan_agent_artifact_dirs(projects_root, [artifact_dir])
    assert len(snapshot.records) == 1
    return snapshot.records[0]


def _compact_identity(full_record: Any, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "project_name": full_record.project_name,
        "project_dir": full_record.project_dir,
        "project_file": full_record.project_file,
        "workflow_dir_name": full_record.workflow_dir_name,
        "artifact_dir": full_record.artifact_dir,
        "timestamp": full_record.timestamp,
        "has_done_marker": full_record.has_done_marker,
        "record_shape": "compact",
    }
    record.update(overrides)
    return record


RICH_META = {
    "name": "rich-agent",
    "cl_name": "cl-rich",
    "process_identity": "proc-1",
    "model": "gpt-5.6-sol",
    "llm_provider": "codex",
    "vcs_provider": "github",
    "workspace_dir": "/tmp/ws-rich",
    "workspace_num": 7,
    "plan_path": "/tmp/plan.md",
    "sdd_plan_path": "/tmp/sdd.md",
    "epic_plan_ref": "plan:202611/x.md",
    "plan": True,
    "plan_action": "execute",
    "plan_submitted_at": ["2026-11-17T11:00:00Z"],
    "epic_bead_id": "sase-1t3",
    "phase_bead_id": "sase-1t3.10",
    "created_epics": [{"bead_id": "sase-9", "project": "sase"}],
    "commit_diff_path": "/tmp/commit.diff",
    "tribe": "bench",
    "agent_tab": "review",
    "wait_for": ["other-agent"],
    "wait_for_beads": ["sase-2"],
    "wait_duration": 60.0,
    "queue_capacity": 2,
    "queue_capacity_explicit": True,
    "wait_priority": 5,
    "approve": True,
    "auto_approve_plan_action": "execute",
    "hidden": False,
    "role_suffix": "plan",
    "agent_session": "session-7",
    "agent_session_role": "code",
    "agent_clan": "clan-1",
    "agent_clan_generation": "g2",
    "clan_tribe": "chop",
    "clan_summary": "chopping",
    "parent_timestamp": "20261117110000",
    "retry_of_timestamp": "20261117100000",
    "retry_attempt": 1,
    "retry_chain_root_timestamp": "20261117090000",
    "retried_as_timestamp": "20261117130000",
    "retry_terminal": False,
    "retry_error_category": "timeout",
    "retry_started_at": ["2026-11-17T10:30:00Z"],
    "epic_started_at": "2026-11-17T10:00:00Z",
    "feedback_submitted_at": ["2026-11-17T10:15:00Z"],
    "questions_submitted_at": ["2026-11-17T10:20:00Z"],
    "run_started_at": "2026-11-17T11:00:01Z",
    "stopped_at": "2026-11-17T12:00:00Z",
    "question_request_path": "/tmp/q/request.json",
    "question_session_id": "qs-1",
    "imported_source_owner": {"username": "bryan", "machine_name": "apollo"},
    "source_machine": "apollo",
    "output_path": "/tmp/out.log",
    "auto_restart": {"evidence_dir": "/tmp/ev"},
    "finalizer_status": {
        "phase": "executing",
        "status": "running",
        "updated_at": 1.5,
        "instance_count": 1,
        "instances": [
            {"id": "fin-1", "status": "running", "op": "declare", "step": "s1"}
        ],
    },
}

RICH_COMPACT_META = dict(RICH_META)


def _rich_done_json() -> dict[str, Any]:
    return {
        "outcome": "completed",
        "cl_name": "cl-rich",
        "workspace_num": 7,
        "workspace_dir": "/tmp/ws-rich",
        "model": "gpt-5.6-sol",
        "llm_provider": "codex",
        "vcs_provider": "github",
        "name": "rich-agent",
        "plan_path": "/tmp/plan.md",
        "diff_path": "/tmp/done.diff",
        "step_output": {
            "meta_workspace": "7",
            "meta_commit_message": "rich commit",
            "diff_path": "/tmp/done.diff",
        },
        "markdown_pdf_paths": ["/tmp/deferred.pdf"],
        "response_path": "/tmp/response.md",
        "imported_source_owner": {"username": "bryan", "machine_name": "apollo"},
        "source_machine": "apollo",
    }


def _rich_compact_done() -> dict[str, Any]:
    return {
        "outcome": "completed",
        "cl_name": "cl-rich",
        "workspace_num": 7,
        "workspace_dir": "/tmp/ws-rich",
        "model": "gpt-5.6-sol",
        "llm_provider": "codex",
        "vcs_provider": "github",
        "name": "rich-agent",
        "plan_path": "/tmp/plan.md",
        "diff_path": "/tmp/done.diff",
        "step_output": {
            "meta": {
                "meta_workspace": "7",
                "meta_commit_message": "rich commit",
            },
            "diff_path": "/tmp/done.diff",
        },
        "imported_source_owner": {"username": "bryan", "machine_name": "apollo"},
        "source_machine": "apollo",
    }


def test_completed_row_parity(tmp_path: Path) -> None:
    ts = "20261117120000"
    projects_root, artifact_dir = _layout(tmp_path, "proj", "ace-run", ts)
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": dict(RICH_META),
            "done.json": _rich_done_json(),
            "waiting.json": {
                "waiting_for": ["other-agent"],
                "wait_duration": 60.0,
                "queue_capacity": 2,
                "queue_capacity_explicit": True,
                "wait_priority": 5,
                "slot_requested_at": "2026-11-17T11:30:00Z",
            },
            "pending_question.json": {
                "session_id": "qs-1",
                "request_path": "/tmp/q/request.json",
            },
            "plan_path.json": {"plan_path": "/tmp/p.md"},
            "prompt_step_a.json": {
                "output": {"meta_prompt": "keep", "other": "dropped?"}
            },
        },
    )
    full_record = _scan_full(projects_root, artifact_dir)
    full = build_done_agent_from_record(full_record, {}, {})

    compact_record = _compact_identity(
        full_record,
        meta=dict(RICH_COMPACT_META),
        done=_rich_compact_done(),
        waiting={
            "waiting_for": ["other-agent"],
            "wait_duration": 60.0,
            "queue_capacity": 2,
            "queue_capacity_explicit": True,
            "wait_priority": 5,
            "slot_requested_at": "2026-11-17T11:30:00Z",
        },
        pending_question={
            "session_id": "qs-1",
            "request_path": "/tmp/q/request.json",
        },
        plan_path="/tmp/p.md",
        prompt_steps=[
            {
                "file_name": "prompt_step_a.json",
                "step_name": "s",
                "step_type": "agent",
                "status": "done",
                "output": {"meta": {"meta_prompt": "keep"}},
            }
        ],
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    compact = _build_done_agent_from_compact_record(decoded, {}, {})

    _assert_parity(full, compact)
    # Deferred: full row carries the PDF and response path; compact does not.
    # (Both rows share the auto-restart provenance evidence entry.)
    assert full is not None and compact is not None
    assert "/tmp/deferred.pdf" in full.extra_files
    assert "/tmp/deferred.pdf" not in compact.extra_files
    assert full.extra_files[0] == compact.extra_files[0] == "/tmp/plan.md"
    assert full.response_path == "/tmp/response.md"
    assert full.response_path == "/tmp/response.md"
    # Terminal done rows keep DONE even with a waiting marker present: the
    # waiting override only applies to active (STARTING/RUNNING) rows on
    # both paths. The question marker likewise only flips active rows.
    assert compact.status == "DONE"
    # meta_workspace flows through reconstructed step output.
    assert compact.effective_workspace_num == 7


def test_failed_retried_row_parity(tmp_path: Path) -> None:
    ts = "20261117120100"
    projects_root, artifact_dir = _layout(tmp_path, "proj", "run", ts)
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "fail-agent", "cl_name": "cl-fail"},
            "done.json": {
                "outcome": "failed",
                "cl_name": "cl-fail",
                "error": "boom",
                "traceback": "Traceback: ...",
                "retried_as_timestamp": "20261117120200",
                "retry_chain_root_timestamp": ts,
                "retry_error_category": "timeout",
                "recovery": {
                    "state": "declined",
                    "reason": "manual",
                    "episode_id": "ep-1",
                },
            },
        },
    )
    full_record = _scan_full(projects_root, artifact_dir)
    full = build_done_agent_from_record(full_record, {}, {})

    compact_record = _compact_identity(
        full_record,
        meta={"name": "fail-agent", "cl_name": "cl-fail"},
        done={
            "outcome": "failed",
            "cl_name": "cl-fail",
            "error": "boom",
            "retried_as_timestamp": "20261117120200",
            "retry_chain_root_timestamp": ts,
            "retry_error_category": "timeout",
            "recovery": {
                "state": "declined",
                "reason": "manual",
                "episode_id": "ep-1",
            },
        },
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    compact = _build_done_agent_from_compact_record(decoded, {}, {})

    _assert_parity(full, compact)
    assert compact is not None and compact.status == "FAILED (RETRIED)"
    assert compact.recovery_state == "declined"


def test_monitored_row_parity(tmp_path: Path) -> None:
    ts = "20261117120300"
    projects_root, artifact_dir = _layout(tmp_path, "proj", "ace-run", ts)
    monitor_turn = {
        "kind": "monitor",
        "id": "mon-1",
        "state": "settled",
        "stop_status": "MONITORED",
        "followup_outcome": "done",
        "host_completion_status": "ok",
        "monitor": {"exit_code": 0, "command": "deferred-cmd"},
    }
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {
                "name": "mon-agent",
                "cl_name": "cl-mon",
                "run_started_at": "2026-11-17T11:00:01Z",
                "agent_session": "sess-mon",
                "agent_session_role": "monitor",
            },
            "done.json": {
                "outcome": "monitored",
                "cl_name": "cl-mon",
                "status_label": "MONITORED",
                "agent_session_turn": monitor_turn,
            },
        },
    )
    full_record = _scan_full(projects_root, artifact_dir)
    full = build_done_agent_from_record(full_record, {}, {})

    compact_turn = {
        "kind": "monitor",
        "id": "mon-1",
        "state": "settled",
        "stop_status": "MONITORED",
        "followup_outcome": "done",
        "host_completion_status": "ok",
        "monitor": {"exit_code": 0},
    }
    compact_record = _compact_identity(
        full_record,
        meta={
            "name": "mon-agent",
            "cl_name": "cl-mon",
            "run_started_at": "2026-11-17T11:00:01Z",
            "agent_session": "sess-mon",
            "agent_session_role": "monitor",
        },
        done={
            "outcome": "monitored",
            "cl_name": "cl-mon",
            "status_label": "MONITORED",
            "agent_session_turn": compact_turn,
        },
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    compact = _build_done_agent_from_compact_record(decoded, {}, {})

    assert full is not None and compact is not None
    assert full.status == "MONITORED" == compact.status
    # The done-turn monitor command flows on neither path (the full done
    # branch never forwards it); only meta-turn commands reach the row.
    assert full.monitor_command is None
    assert compact.monitor_command is None
    assert _facts(full) == _facts(compact)


def test_hijacked_expired_row_parity(tmp_path: Path) -> None:
    ts = "20261117120400"
    projects_root, artifact_dir = _layout(tmp_path, "proj", "ace-run", ts)
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "hj", "cl_name": "cl-hj"},
            "done.json": {
                "outcome": "hijacked",
                "cl_name": "cl-hj",
                "recovery": {"state": "expired", "hijack_id": "h-1"},
            },
        },
    )
    full_record = _scan_full(projects_root, artifact_dir)
    full = build_done_agent_from_record(full_record, {}, {})

    compact_record = _compact_identity(
        full_record,
        meta={"name": "hj", "cl_name": "cl-hj"},
        done={
            "outcome": "hijacked",
            "cl_name": "cl-hj",
            "recovery": {"state": "expired", "hijack_id": "h-1"},
        },
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    compact = _build_done_agent_from_compact_record(decoded, {}, {})

    _assert_parity(full, compact)
    assert compact is not None and compact.hijack_expired is True


def test_noop_row_builds_nothing(tmp_path: Path) -> None:
    ts = "20261117120500"
    projects_root, artifact_dir = _layout(tmp_path, "proj", "ace-run", ts)
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "np", "cl_name": "cl-np"},
            "done.json": {"outcome": "noop", "cl_name": "cl-np"},
        },
    )
    full_record = _scan_full(projects_root, artifact_dir)
    assert build_done_agent_from_record(full_record, {}, {}) is None

    compact_record = _compact_identity(
        full_record,
        meta={"name": "np", "cl_name": "cl-np"},
        done={"outcome": "noop", "cl_name": "cl-np"},
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    assert _build_done_agent_from_compact_record(decoded, {}, {}) is None


def test_snapshot_loaders_agree_on_row_sets(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    dirs: list[Path] = []
    for offset, outcome in (
        ("20261117121000", "completed"),
        ("20261117121100", "noop"),
    ):
        artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / offset
        _write_markers(
            artifact_dir,
            {
                "agent_meta.json": {"name": f"a-{offset}", "cl_name": "cl-x"},
                "done.json": {"outcome": outcome, "cl_name": "cl-x"},
            },
        )
        dirs.append(artifact_dir)
    full_snapshot = scan_agent_artifact_dirs(projects_root, dirs)
    full_agents = load_done_agents_from_snapshot(full_snapshot, {}, {})

    compact_snapshot = agent_artifact_list_scan_wire_from_dict(
        {
            "schema_version": 1,
            "projects_root": str(projects_root),
            "options": {},
            "stats": {},
            "records": [
                _compact_identity(
                    record,
                    meta={"name": f"a-{record.timestamp}", "cl_name": "cl-x"},
                    done={"outcome": outcome, "cl_name": "cl-x"},
                )
                for record, outcome in zip(
                    full_snapshot.records, ("completed", "noop"), strict=True
                )
            ],
        }
    )
    compact_agents = load_done_agents_from_compact_snapshot(compact_snapshot, {}, {})
    assert len(full_agents) == len(compact_agents) == 1
    _assert_parity(full_agents[0], compact_agents[0])


def test_running_home_row_parity(tmp_path: Path) -> None:
    ts = "20261117122000"
    projects_root, artifact_dir = _layout(tmp_path, "home", "ace-run", ts)
    live_pid = os.getpid()
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {
                "name": "home-agent",
                "cl_name": "cl-home",
                "run_started_at": "2026-11-17T11:00:01Z",
                "model": "gpt-5.6-sol",
            },
            "running.json": {
                "pid": live_pid,
                "cl_name": "cl-home",
                "model": "gpt-5.6-sol",
                "llm_provider": "codex",
                "workspace_dir": "/tmp/ws-home",
            },
            "waiting.json": {"waiting_for": ["slot-1"]},
        },
    )
    full_snapshot = scan_agent_artifact_dirs(projects_root, [artifact_dir])
    full_agents = load_running_home_agents_from_snapshot(full_snapshot)
    assert len(full_agents) == 1

    compact_record = _compact_identity(
        full_snapshot.records[0],
        meta={
            "name": "home-agent",
            "cl_name": "cl-home",
            "run_started_at": "2026-11-17T11:00:01Z",
            "model": "gpt-5.6-sol",
        },
        running={
            "pid": live_pid,
            "cl_name": "cl-home",
            "model": "gpt-5.6-sol",
            "llm_provider": "codex",
            "workspace_dir": "/tmp/ws-home",
        },
        waiting={"waiting_for": ["slot-1"]},
    )
    (decoded,) = agent_artifact_list_records_from_dicts([compact_record])
    compact_agents = _load_running_home_agents_from_compact_records(
        _resolve_compact_running_home_records(
            agent_artifact_list_scan_wire_from_dict(
                {
                    "schema_version": 1,
                    "projects_root": str(projects_root),
                    "options": {},
                    "stats": {},
                    "records": [compact_record],
                }
            )
        ),
        project_file=full_agents[0].project_file,
    )
    assert len(compact_agents) == 1
    _assert_parity(full_agents[0], compact_agents[0])
    assert compact_agents[0].status == "WAITING"


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("full-record path must not be used")


def test_compact_path_does_not_use_full_decoder(monkeypatch: Any) -> None:
    monkeypatch.setattr("sase.core.agent_scan_wire_conversion._record_from_dict", _boom)
    monkeypatch.setattr(
        "sase.core.agent_scan_wire_conversion.agent_scan_wire_from_dict", _boom
    )
    record = {
        "project_name": "home",
        "project_dir": "/tmp/x/home",
        "project_file": "/tmp/x/home/home.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/x/home/artifacts/ace-run/20261117120000",
        "timestamp": "20261117120000",
        "has_done_marker": True,
        "record_shape": "compact",
        "meta": {"name": "bob", "run_started_at": "2026-11-17T11:00:01Z"},
        "done": {"outcome": "completed", "cl_name": "cl1"},
    }
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    agent = _build_done_agent_from_compact_record(decoded, {}, {})
    assert agent is not None and agent.status == "DONE"


def test_compact_constructors_do_not_call_full_loaders(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._done_snapshot_loaders."
        "build_done_agent_from_record",
        _boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._meta_enrichment_wire."
        "enrich_agent_from_meta_wire",
        _boom,
    )
    ts = "20261117123000"
    projects_root, artifact_dir = _layout(tmp_path, "home", "ace-run", ts)
    live_pid = os.getpid()
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "g", "cl_name": "cl-g"},
            "running.json": {"pid": live_pid, "cl_name": "cl-g"},
        },
    )
    full_snapshot = scan_agent_artifact_dirs(projects_root, [artifact_dir])
    compact_record = _compact_identity(
        full_snapshot.records[0],
        meta={"name": "g", "cl_name": "cl-g"},
        running={"pid": live_pid, "cl_name": "cl-g"},
    )
    snapshot = agent_artifact_list_scan_wire_from_dict(
        {
            "schema_version": 1,
            "projects_root": str(projects_root),
            "options": {},
            "stats": {},
            "records": [compact_record],
        }
    )
    agents = load_running_home_agents_from_compact_snapshot(snapshot)
    assert len(agents) == 1 and agents[0].cl_name == "cl-g"
