"""Tests for the `tools/selection_health` CLI wrapper.

The CLI is driven against a synthetic record store under ``tmp_path``, so
nothing here depends on whatever runs this host happens to have recorded.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection_health import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    record_selection,
    write_record,
)


# Deliberately *not* contract-marked. The contract set is a fixed tax on every
# scoped check, and this module reports on health rather than gating a landing:
# a change to `tests/_test_selection_health.py` selects it through the import
# graph anyway, and a change to `tools/selection_health` alone is caught by CI
# within ~15 minutes. Err small.

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "selection_health"
NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("selection_health_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "selection_health_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _populate(store: Path, *, missed: bool) -> None:
    record_selection(
        store,
        {
            "schema": 1,
            "escalated": False,
            "rules_fired": ["contract-set-always"],
            "selected": ["tests/test_kept.py"],
            "selected_count": 1,
            "universe_count": 2400,
            "duration": 80.0,
            "outcome": "passed",
            "baseline": {"head": "aaa"},
        },
        pid=1,
        now=NOW,
    )
    if not missed:
        return
    path = allocate_record_path(store, KIND_FULL_RUN, head="bbb", pid=2, now=NOW)
    write_record(
        path,
        full_run_record(
            head="bbb",
            mode="fast",
            failures=["tests/test_missed.py::test_x"],
            exit_status=1,
            now=NOW,
        ),
    )


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_report_reads_the_requested_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _populate(store, missed=False)
    tool = _load_tool()

    assert tool.main(["--store", str(store)]) == 0

    output = capsys.readouterr().out
    assert str(store) in output
    assert "scoped runs recorded:   1" in output
    assert "false negatives: 0" in output


def test_json_output_is_parseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _populate(store, missed=False)
    tool = _load_tool()

    assert tool.main(["--store", str(store), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scoped_runs"] == 1
    assert payload["escalated_runs"] == 0
    assert payload["false_negatives"] == []


def test_empty_store_reports_rather_than_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _load_tool()

    assert tool.main(["--store", str(tmp_path / "nothing")]) == 0
    assert "No runs recorded yet." in capsys.readouterr().out


def test_fail_on_false_negative_is_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"
    _populate(store, missed=True)
    tool = _load_tool()
    monkeypatch.setattr(tool, "git_ancestor_oracle", lambda _root: lambda _a, _b: True)

    assert tool.main(["--store", str(store)]) == 0
    assert "false negatives: 1" in capsys.readouterr().out
    assert tool.main(["--store", str(store), "--fail-on-false-negative"]) == 1
