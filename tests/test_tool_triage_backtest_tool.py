"""Tests for the read-only `tools/tool_triage_backtest` replay tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "tool_triage_backtest"


def test_empty_ledger_writes_report_and_audit_without_creating_store(
    tmp_path: Path,
) -> None:
    store = tmp_path / "tools" / "runs.sqlite"
    out_dir = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "--store",
            str(store),
            "--artifacts-root",
            str(tmp_path / "artifacts"),
            "--selection-dir",
            str(tmp_path / "selection"),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    counts = {"known_items": 0, "known_on_added_or_untracked": 0, "selected_runs": 0}
    assert json.loads(completed.stdout) == counts
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["counts"] == counts
    assert report["sample"] == []
    assert (
        (out_dir / "audit.md")
        .read_text(encoding="utf-8")
        .startswith("# Triage backtest audit\n")
    )
    assert not store.exists()
