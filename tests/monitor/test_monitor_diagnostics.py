"""Monitor diagnostic evidence capture tests."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from sase.monitor.diagnostics import (
    freeze_retained_log_metadata,
    read_diagnostics_text,
    read_retained_log_range,
    read_selected_diagnostics_text,
    retained_log_metadata,
)
from sase.monitor.supervise import run_supervisor

from ._fixtures import isolate_from_enclosing_run, without_tool_run_recording
from ._supervise import _make_member, _restore_signal_handlers, _sandbox_home


def test_freeze_without_retention_assigns_ranges_to_rotated_and_active_logs(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    output_path = tmp_path / "live_reply.md"
    output_path.with_name("live_reply.md.1").write_bytes(b"older\n")
    output_path.write_bytes(b"newer\n")

    metadata = freeze_retained_log_metadata(
        artifacts_dir,
        output_path=output_path,
        monitor_id="monitor-test",
        retention=None,
    )

    assert [segment["range"] for segment in metadata["segments"]] == [
        {"start": 0, "end": 6},
        {"start": 6, "end": 12},
    ]
    assert metadata["retained_ranges"] == [
        {"start": 0, "end": 6},
        {"start": 6, "end": 12},
    ]
    ranged = read_retained_log_range(artifacts_dir, start=0, end=12)
    assert ranged.text == "older\nnewer\n"


def test_freeze_without_retention_assigns_range_to_active_only_log(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    output_path = tmp_path / "live_reply.md"
    output_path.write_bytes(b"active only\n")

    metadata = freeze_retained_log_metadata(
        artifacts_dir,
        output_path=output_path,
        monitor_id="monitor-active",
        retention=None,
    )

    assert metadata["segments"][0]["range"] == {"start": 0, "end": 12}
    assert metadata["retained_ranges"] == [{"start": 0, "end": 12}]
    assert (
        read_retained_log_range(artifacts_dir, start=0, end=12).text == "active only\n"
    )


def test_read_retained_log_range_supports_legacy_null_segment_ranges(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    retained = artifacts_dir / "diagnostics" / "retained_logs" / "monitor.log"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"legacy bytes\n")
    metadata_path = artifacts_dir / "diagnostics" / "retained_log_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "complete": True,
                "drain_confirmed": True,
                "segments": [
                    {
                        "locator": "diagnostics/retained_logs/monitor.log",
                        "bytes": 13,
                        "range": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    ranged = read_retained_log_range(artifacts_dir, start=0, end=13)

    assert ranged.text == "legacy bytes\n"
    assert ranged.metadata["missing_ranges"] == []


def _run_silent_path() -> Path:
    return Path(__file__).parents[2] / "tools" / "run_silent"


def test_run_silent_writes_isolated_monitor_stage_report(tmp_path: Path) -> None:
    diagnostics_dir = tmp_path / "artifacts" / "diagnostics"
    env = without_tool_run_recording(os.environ)
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
    assert type(report["started_at_epoch"]) is float
    assert type(report["elapsed_seconds"]) is float
    assert report["elapsed_seconds"] >= 0
    assert report["started_at_epoch"] <= report["recorded_at_epoch"]
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
    isolate_from_enclosing_run(monkeypatch)
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

    result_path = Path(meta["continuation_monitor_result_path"])
    assert result_path.exists()
    monitor_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert monitor_result["outcome"] == "failed"
    assert monitor_result["exit_code"] == 4
    assert monitor_result["diagnostic_manifest_ref"] == manifest["manifest_ref"]
    assert monitor_result["retained_log"]["log_ref"] == metadata["log_ref"]
    assert meta["continuation_monitor_result_node_ref"].startswith(
        "local:continuation/nodes/"
    )

    first_range = metadata["retained_ranges"][0]
    ranged = read_retained_log_range(
        artifacts_dir,
        start=int(first_range["start"]),
        end=int(first_range["end"]),
    )
    assert ranged.metadata["available"] is True
    assert "retained output gap" not in ranged.text
    # A 64-byte cap plus a 120-x payload freezes either the stage banner
    # (drain interleaves) or the truncated x-tail (one oversized chunk).
    assert "test (scoped)" in ranged.text or ("x" * 16) in ranged.text
    last_range = metadata["retained_ranges"][-1]
    tail = read_retained_log_range(
        artifacts_dir,
        start=int(last_range["start"]),
        end=int(last_range["end"]),
    )
    assert ("x" * 16) in tail.text
    assert "retained output gap" not in tail.text


def test_selected_diagnostics_reads_only_rust_selected_stage_locators(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    selected_path = artifacts_dir / "diagnostics" / "stage_output" / "pytest.log"
    other_path = artifacts_dir / "diagnostics" / "stage_output" / "ruff.log"
    selected_path.parent.mkdir(parents=True)
    selected_path.write_text("pytest boom\nUNICODE SENTINEL: \u03b1\u03b2\u03b3\n")
    other_path.write_text("ruff should stay out\n")
    manifest = {
        "schema_version": 1,
        "producer": "test",
        "complete": False,
        "stages": [
            {
                "stage_id": "ruff",
                "name": "ruff",
                "status": "failed",
                "exit_code": 1,
                "diagnostic_locators": ["diagnostics/stage_output/ruff.log"],
            },
            {
                "stage_id": "pytest",
                "name": "pytest",
                "status": "failed",
                "exit_code": 7,
                "diagnostic_locators": ["diagnostics/stage_output/pytest.log"],
                "counts": {"failures": 2, "output_bytes": 40},
            },
        ],
    }

    selected = read_selected_diagnostics_text(
        artifacts_dir,
        selection={
            "diagnostic_stage_ids": ["pytest"],
            "max_embedded_bytes": 256,
        },
        manifest=manifest,
    )
    limited = read_selected_diagnostics_text(
        artifacts_dir,
        selection={
            "diagnostic_stage_ids": ["pytest"],
            "max_embedded_bytes": len(b"== pytest (failed exit 7) ==\n") + 1,
        },
        manifest=manifest,
    )

    assert "pytest boom" in selected.text
    assert "UNICODE SENTINEL" in selected.text
    assert "failures=2" in selected.text
    assert "ruff should stay out" not in selected.text
    assert selected.metadata["selected_stages"][0]["stage_id"] == "pytest"
    limited.text.encode("utf-8")
