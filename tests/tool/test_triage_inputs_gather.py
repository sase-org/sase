"""Selection-record gathering for durable triage inputs."""

from __future__ import annotations

import importlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sase.core.tool_run import tool_run_triage_extract
from sase.tool.triage_inputs import gather_selection_records
from tests.tool._triage_inputs_helpers import NODE, home, write_full_run

pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)


def test_gather_selection_records_emits_wire_valid_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    write_full_run(
        selection_dir,
        head="abc123def456",
        failures=[NODE],
        recorded_at=now,
    )
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        project="fixture",
        tool="check",
        extra_args_digest="",
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    assert len(records) == 1
    record = records[0]
    assert "failures" not in record
    assert record["selection_source"] is True
    assert record["items"]
    item = record["items"][0]
    assert set(item) <= {"extractor", "extractor_version", "signature", "stage_key"}
    assert item["extractor"] == "pytest"
    assert item["stage_key"] == "test (scoped)"
    expected = tool_run_triage_extract(
        {
            "stage_key": "test (scoped)",
            "output": f"FAILED {NODE}",
            "project_root": str(tmp_path),
        }
    )["items"][0]
    assert item["signature"] == expected["signature"]


def test_gather_selection_records_skips_old_mtime_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    stale = write_full_run(
        selection_dir,
        head="deadbeef0001",
        failures=[NODE],
        recorded_at=now,
        pid=1,
    )
    fresh = write_full_run(
        selection_dir,
        head="deadbeef0002",
        failures=["tests/test_fresh.py::test_ok"],
        recorded_at=now,
        pid=2,
    )
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))
    records, _diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert [row["base_head"] for row in records] == ["deadbeef0002"]
    assert fresh.exists()


def test_gather_selection_records_empty_failures_are_empty_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    write_full_run(selection_dir, head="abc123", failures=[], recorded_at=now)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    assert records[0]["items"] == []
    assert "failures" not in records[0]


def test_gather_selection_records_extraction_error_drops_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    write_full_run(selection_dir, head="abc123", failures=[NODE], recorded_at=now)

    def _boom(_request: object) -> dict[str, Any]:
        raise RuntimeError("extract boom")

    monkeypatch.setattr("sase.tool.triage_inputs.tool_run_triage_extract", _boom)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert records[0]["items"] == []
    assert any("extract boom" in note for note in diagnostics)
