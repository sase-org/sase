"""Output writers and CLI for ``tools/render_visual_snapshot_failure_report``.

Covers ``write_outputs``, ``write_outputs_from_manifest``, and the script's
``main`` entry point. Pure-renderer coverage lives in
``tests/test_render_visual_snapshot_failure_report.py``; shared builders live
in ``tests/_render_visual_snapshot_failure_report_helpers.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests._render_visual_snapshot_failure_report_helpers import (
    SCRIPT_PATH,
    failure_png,
    load_script,
    write_failure,
)


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return load_script()


# ---------------------------------------------------------------------------
# write_outputs / CLI
# ---------------------------------------------------------------------------


def test_write_outputs_writes_all_four_files(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    monkeypatch.chdir(tmp_path)
    records = list(script.discover_records(artifact_root))
    output_dir = tmp_path / "report"
    context = script.RenderContext(repo="owner/name", sha="deadbeef", report_url=None)

    script.write_outputs(records, output_dir=output_dir, context=context)

    assert (output_dir / "visual-failure-report.html").exists()
    assert (output_dir / "summary.md").exists()
    assert (output_dir / "annotations.sh").exists()
    assert (output_dir / "manifest.jsonl").exists()


def test_write_outputs_no_records_writes_empty_outputs(
    tmp_path: Path, script: types.ModuleType
) -> None:
    output_dir = tmp_path / "report"
    context = script.RenderContext(repo=None, sha=None, report_url=None)

    script.write_outputs([], output_dir=output_dir, context=context)

    html_text = (output_dir / "visual-failure-report.html").read_text()
    assert "No sase's TUI PNG snapshot failures" in html_text
    assert (
        (output_dir / "summary.md")
        .read_text()
        .startswith("# sase's TUI PNG snapshot failures")
    )
    assert (output_dir / "annotations.sh").read_text().startswith("#!/usr/bin/env bash")
    assert (output_dir / "manifest.jsonl").read_text() == ""


def test_write_outputs_from_manifest_reports_created_updated_and_stale(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL.Image")
    repo = tmp_path
    monkeypatch.chdir(repo)
    run_dir = repo / ".pytest_cache/sase-visual/runs/run1"
    capture_dir = run_dir / "capture"
    capture_dir.mkdir(parents=True)
    red = failure_png((255, 0, 0, 255))
    blue = failure_png((0, 0, 255, 255))
    green = failure_png((0, 255, 0, 255))
    created_candidate = capture_dir / "workers/controller/candidates/created.png"
    updated_candidate = capture_dir / "workers/controller/candidates/updated.png"
    updated_candidate_2 = capture_dir / "workers/controller/candidates/updated2.png"
    created_candidate.parent.mkdir(parents=True)
    created_candidate.write_bytes(green)
    updated_candidate.write_bytes(blue)
    updated_candidate_2.write_bytes(blue)
    (created_candidate.parent / "created.svg").write_text("<svg>created</svg>")
    baseline_one = run_dir / "baseline/tests/ace/tui/visual/snapshots/png/updated.png"
    baseline_two = run_dir / "baseline/tests/ace/tui/visual/snapshots/png/updated2.png"
    stale_baseline = run_dir / "baseline/tests/pager/visual/snapshots/png/stale.png"
    baseline_one.parent.mkdir(parents=True)
    baseline_two.parent.mkdir(parents=True, exist_ok=True)
    stale_baseline.parent.mkdir(parents=True)
    baseline_one.write_bytes(red)
    baseline_two.write_bytes(red)
    stale_baseline.write_bytes(red)
    manifest = {
        "schema_version": 1,
        "kind": "visual_maintenance",
        "run_id": "run1",
        "mode": "check",
        "status": "drift",
        "requested_scope": "full",
        "counts": {"created": 1, "updated": 2, "unchanged": 0, "stale": 1},
        "dirty_before": ["tests/ace/tui/visual/snapshots/png/dirty.png"],
        "manifest_path": ".pytest_cache/sase-visual/runs/run1/manifest.json",
        "run_dir": ".pytest_cache/sase-visual/runs/run1",
        "capture_dir": ".pytest_cache/sase-visual/runs/run1/capture",
        "errors": [],
        "changes": [
            {
                "kind": "created",
                "path": "tests/ace/tui/visual/snapshots/png/created.png",
                "root_identity": "ace",
                "node_id": "tests/ace/tui/visual/test_a.py::test_created",
                "snapshot_name": "created",
                "candidate_png_relpath": ("workers/controller/candidates/created.png"),
                "candidate_svg_relpath": ("workers/controller/candidates/created.svg"),
                "candidate_width": 1,
                "candidate_height": 1,
                "total_pixels": 1,
                "test_file": "tests/ace/tui/visual/test_a.py",
                "test_line": 12,
            },
            {
                "kind": "updated",
                "path": "tests/ace/tui/visual/snapshots/png/updated.png",
                "root_identity": "ace",
                "node_id": "tests/ace/tui/visual/test_a.py::test_updated",
                "snapshot_name": "updated",
                "candidate_png_relpath": ("workers/controller/candidates/updated.png"),
                "baseline_width": 1,
                "baseline_height": 1,
                "candidate_width": 1,
                "candidate_height": 1,
                "changed_pixels": 1,
                "total_pixels": 1,
                "test_file": "tests/ace/tui/visual/test_a.py",
                "test_line": 21,
            },
            {
                "kind": "updated",
                "path": "tests/ace/tui/visual/snapshots/png/updated2.png",
                "root_identity": "ace",
                "node_id": "tests/ace/tui/visual/test_a.py::test_updated2",
                "snapshot_name": "updated2",
                "candidate_png_relpath": ("workers/controller/candidates/updated2.png"),
                "baseline_width": 1,
                "baseline_height": 1,
                "candidate_width": 1,
                "candidate_height": 1,
                "changed_pixels": 1,
                "total_pixels": 1,
            },
            {
                "kind": "stale",
                "path": "tests/pager/visual/snapshots/png/stale.png",
                "root_identity": "pager",
                "baseline_width": 1,
                "baseline_height": 1,
                "total_pixels": 1,
            },
        ],
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output_dir = run_dir / "report"

    metadata = script.write_outputs_from_manifest(
        manifest_path,
        output_dir=output_dir,
        context=script.RenderContext(repo=None, sha=None, report_url=None),
        repo_root=repo,
    )

    assert metadata["record_count"] == 4
    assert metadata["groups"][0]["size"] == 2
    assert (output_dir / "images").is_dir()
    assert (output_dir / "contact-sheet.png").is_file()
    html = (output_dir / "visual-failure-report.html").read_text()
    assert "no baseline image existed" in html
    assert "no producing assertion" in html
    assert "group-1" in html
    entries = [
        json.loads(line)
        for line in (output_dir / "manifest.jsonl").read_text().splitlines()
    ]
    assert {entry["kind"] for entry in entries} == {"created", "updated", "stale"}
    updated = [entry for entry in entries if entry["kind"] == "updated"]
    assert {entry["group_id"] for entry in updated} == {"group-1"}


def test_write_outputs_from_manifest_renders_partial_and_not_updated(
    tmp_path: Path, script: types.ModuleType
) -> None:
    repo = tmp_path
    run_dir = repo / ".pytest_cache/sase-visual/runs/run-partial"
    run_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "kind": "visual_maintenance",
        "run_id": "run-partial",
        "mode": "update",
        "status": "partial",
        "requested_scope": "full",
        "counts": {"created": 0, "updated": 0, "unchanged": 1, "stale": 0},
        "dirty_before": [],
        "manifest_path": ".pytest_cache/sase-visual/runs/run-partial/manifest.json",
        "run_dir": ".pytest_cache/sase-visual/runs/run-partial",
        "capture_dir": ".pytest_cache/sase-visual/runs/run-partial/capture",
        "errors": [],
        "warnings": ["stale removal skipped: evidence is incomplete"],
        "skipped": [
            {
                "kind": "node",
                "node_id": "tests/ace/tui/visual/test_a.py::test_a",
                "path": None,
                "reason": "test_failed",
                "detail": "test failed and never recovered",
                "evidence": [".pytest_cache/sase-visual/runs/run-partial/capture.log"],
                "attempts": 3,
            }
        ],
        "attempts": [
            {
                "label": "capture",
                "run_id": "run-partial",
                "capture_dir": ".pytest_cache/sase-visual/runs/run-partial/capture",
                "log": ".pytest_cache/sase-visual/runs/run-partial/capture.log",
                "workers": None,
                "child_exit_code": 1,
            }
        ],
        "pruning_skipped_reason": "stale removal skipped: evidence is incomplete",
        "changes": [],
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output_dir = run_dir / "report"

    metadata = script.write_outputs_from_manifest(
        manifest_path,
        output_dir=output_dir,
        context=script.RenderContext(repo=None, sha=None, report_url=None),
        repo_root=repo,
    )

    assert metadata["status"] == "partial"
    assert metadata["skipped_count"] == 1
    summary = (output_dir / "summary.md").read_text(encoding="utf-8")
    assert "update/partial" in summary
    assert "## Not updated" in summary
    assert "test_failed" in summary
    assert "capture.log" in summary
    html = (output_dir / "visual-failure-report.html").read_text(encoding="utf-8")
    assert "Not updated" in html
    assert "test_failed" in html


def test_cli_runs_end_to_end(tmp_path: Path) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    output_dir = tmp_path / "report"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--artifact-root",
            str(artifact_root),
            "--output-dir",
            str(output_dir),
            "--repo",
            "owner/name",
            "--sha",
            "deadbeef",
            "--report-url",
            "https://example.invalid/artifact",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "visual-failure-report.html").exists()
    assert (output_dir / "summary.md").exists()
    assert (output_dir / "annotations.sh").exists()
    assert (output_dir / "manifest.jsonl").exists()


def test_cli_no_records_exits_zero(tmp_path: Path) -> None:
    artifact_root = tmp_path / "empty"
    output_dir = tmp_path / "report"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--artifact-root",
            str(artifact_root),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
