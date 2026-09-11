"""Monitor diagnostic evidence capture tests."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from sase.monitor.diagnostics import (
    read_diagnostics_text,
    read_retained_log_range,
    retained_log_metadata,
)
from sase.monitor.supervise import run_supervisor

from ._supervise import _make_member, _restore_signal_handlers, _sandbox_home


def _run_silent_path() -> Path:
    return Path(__file__).parents[2] / "tools" / "run_silent"


def test_run_silent_writes_isolated_monitor_stage_report(tmp_path: Path) -> None:
    diagnostics_dir = tmp_path / "artifacts" / "diagnostics"
    env = os.environ.copy()
    env["SASE_MONITOR_DIAGNOSTICS_DIR"] = str(diagnostics_dir)
    env["SASE_MONITOR_ID"] = "monitor-test"

    completed = subprocess.run(
        [
            str(_run_silent_path()),
            "test (scoped)",
            "sh",
            "-c",
            "printf 'stage boom\\n'; exit 7",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 7
    assert "stage boom" in completed.stdout
    reports = list((diagnostics_dir / "stages").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["exit_code"] == 7
    assert report["diagnostic_refs"]
    evidence_path = tmp_path / "artifacts" / report["diagnostic_locators"][0]
    assert evidence_path.read_text(encoding="utf-8") == "stage boom\n"

    forced_dir = tmp_path / "forced" / "diagnostics"
    env["SASE_MONITOR_DIAGNOSTICS_DIR"] = str(forced_dir)
    env["SASE_RUN_SILENT_FORCE_CAPTURE_ERROR"] = "1"
    forced = subprocess.run(
        [
            str(_run_silent_path()),
            "lint (ruff)",
            "sh",
            "-c",
            "printf 'still original\\n'; exit 9",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert forced.returncode == 9
    forced_report = json.loads(
        next((forced_dir / "stages").glob("*.json")).read_text(encoding="utf-8")
    )
    assert forced_report["capture_errors"] == ["forced diagnostic capture error"]
    assert forced_report["diagnostic_refs"] == []


def test_supervisor_freezes_stage_manifest_and_retained_log_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_MONITOR_LOG_MAX_BYTES", "64")
    payload = "import sys; print('stage boom'); print('x' * 120); sys.exit(4)"
    command = (
        f"{shlex.quote(str(_run_silent_path()))} 'test (scoped)' "
        f"{shlex.quote(sys.executable)} -c {shlex.quote(payload)}"
    )
    artifacts_dir, _project_file = _make_member(tmp_path, command=command)

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    manifest_path = Path(meta["monitor_diagnostic_manifest_path"])
    retained_path = Path(meta["monitor_retained_log_metadata_path"])
    assert manifest_path.exists()
    assert retained_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["stages"][0]["status"] == "failed"
    assert manifest["stages"][0]["diagnostic_refs"]

    diagnostics = read_diagnostics_text(artifacts_dir)
    assert "stage boom" in diagnostics.text
    assert diagnostics.metadata["available"] is True

    metadata = retained_log_metadata(artifacts_dir)
    assert metadata["total_observed_bytes"] > 0
    assert metadata["retained_ranges"]
    assert metadata["segments"]

    first_range = metadata["retained_ranges"][0]
    ranged = read_retained_log_range(
        artifacts_dir,
        start=int(first_range["start"]),
        end=int(first_range["end"]),
    )
    assert ranged.metadata["available"] is True
