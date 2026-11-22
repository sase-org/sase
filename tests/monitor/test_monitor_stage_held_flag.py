"""Write-side invariant: not-adopted paths mark held; successful readopt clears it."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from sase.axe._run_agent_exec_staged_recovery_shared import write_held_locked
from sase.axe.run_agent_exec_staged_dispatch import _write_held_receipt_locked
from sase.monitor._start_stage_adopt_flow import _launch_from_persisted_payload_locked
from sase.monitor.start_metadata import persist_monitor_running_state
from sase.monitor.start_stage_cleanup import cleanup_staged_monitor


_NOT_ADOPTED_ENTRY_POINTS = (
    ("runner dispatch", _write_held_receipt_locked),
    ("automatic recovery / dead origin", write_held_locked),
    ("explicit readopt failure", _launch_from_persisted_payload_locked),
)


def test_not_adopted_entry_points_run_held_cleanup() -> None:
    for label, fn in _NOT_ADOPTED_ENTRY_POINTS:
        source = inspect.getsource(fn)
        assert "held=True" in source, label
    cleanup_source = inspect.getsource(cleanup_staged_monitor)
    assert "monitor_stage_held" in cleanup_source


def test_persist_monitor_running_state_clears_held_flag(tmp_path: Path) -> None:
    artifacts = tmp_path / "member"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "monitor_id": "m-held",
                "monitor_state": "staged",
                "monitor_stage_held": True,
            }
        )
    )

    persist_monitor_running_state(str(artifacts))

    meta = json.loads((artifacts / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "running"
    assert "monitor_stage_held" not in meta
