from __future__ import annotations

from pathlib import Path

from sase.core.disk_footprint_reap_tool_run import tool_run_reap_step


def test_tool_run_reap_preview_reports_missing_store(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_wire_schema_version",
        lambda: 1,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_store_stats",
        lambda store_path=None: {"exists": False, "run_count": 0},
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_retention_preview",
        lambda request, store_path=None: {
            "schema_version": 1,
            "dry_run": True,
            "summary_rows": 0,
            "detail_rows": 0,
            "file_candidates": [],
            "protected_unsettled": 0,
            "diagnostics": ["tool run store does not exist"],
        },
    )
    step = tool_run_reap_step(apply=False)
    assert step.owner == "tool_run_retention"
    assert step.mode == "dry_run"
    assert "would remove 0 summary row(s)" in step.summary


def test_tool_run_reap_apply_deletes_confined_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    tools = home / "tools"
    log = tools / "logs" / "run-1" / "stdout.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * 12)
    outside = tmp_path / "escape.log"
    outside.write_text("nope", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_wire_schema_version",
        lambda: 1,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_store_stats",
        lambda store_path=None: {"exists": True, "run_count": 1},
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_retention_apply",
        lambda request, store_path=None: {
            "schema_version": 1,
            "dry_run": False,
            "summary_rows": 1,
            "detail_rows": 0,
            "file_candidates": [
                {
                    "kind": "stdout",
                    "run_id": "run-1",
                    "path": str(log),
                    "protected": False,
                    "reason": "log_days",
                },
                {
                    "kind": "stdout",
                    "run_id": "evil",
                    "path": str(outside),
                    "protected": False,
                    "reason": "should be rejected",
                },
            ],
            "protected_unsettled": 0,
            "diagnostics": [],
        },
    )
    step = tool_run_reap_step(apply=True)
    assert step.owner == "tool_run_retention"
    assert not log.exists()
    assert outside.exists()
    assert step.reclaimed_bytes == 12
    assert step.exit_code == 1
    assert step.owner_error is not None
