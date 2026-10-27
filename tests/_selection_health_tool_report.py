"""CLI and report behavior for the selection-health tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._selection_health_tool_helpers import (
    TOOL_PATH,
    WORKSPACE,
    NOW,
    load_tool,
)
from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    record_selection,
    write_record,
)


def _populate(store: Path, *, missed: bool) -> None:
    record_selection(
        store,
        {
            "schema": 2,
            "escalated": False,
            "rules_fired": ["contract-set-always"],
            "selected": ["tests/test_kept.py"],
            "selected_count": 1,
            "universe_count": 2400,
            "duration": 80.0,
            "outcome": "passed",
            "changed_files": ["src/sase/alpha.py"],
            "baseline": {"head": "aaa"},
        },
        workspace=WORKSPACE,
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
            workspace=WORKSPACE,
            changed_files=["src/sase/alpha.py"],
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
    tool = load_tool()

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
    tool = load_tool()

    assert tool.main(["--store", str(store), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scoped_runs"] == 1
    assert payload["escalated_runs"] == 0
    assert payload["false_negatives"] == []


def test_empty_store_reports_rather_than_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = load_tool()

    assert tool.main(["--store", str(tmp_path / "nothing")]) == 0
    assert "No runs recorded yet." in capsys.readouterr().out


def test_fail_on_false_negative_is_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"
    _populate(store, missed=True)
    tool = load_tool()
    monkeypatch.setattr(tool, "git_ancestor_oracle", lambda _root: lambda _a, _b: True)

    assert tool.main(["--store", str(store)]) == 0
    assert "false negatives: 1" in capsys.readouterr().out
    assert tool.main(["--store", str(store), "--fail-on-false-negative"]) == 1
