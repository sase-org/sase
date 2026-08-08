"""Tests for the `tools/selection_health` CLI wrapper.

The CLI is driven against a synthetic record store under ``tmp_path``, so
nothing here depends on whatever runs this host happens to have recorded.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection_health_store import (
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
WORKSPACE = "/workspaces/sase_11"
FLAKE_NODE = "tests/test_flaky.py::test_x"


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


def _write_full_run(
    store: Path,
    *,
    minute: int,
    changed_files: list[str],
    failures: list[str],
) -> None:
    when = NOW + timedelta(minutes=minute)
    path = allocate_record_path(
        store, KIND_FULL_RUN, head=f"h{minute}", pid=minute, now=when
    )
    write_record(
        path,
        full_run_record(
            head=f"h{minute}",
            mode="fast",
            failures=failures,
            exit_status=1,
            workspace=WORKSPACE,
            changed_files=changed_files,
            now=when,
        ),
    )


def _baseline(
    path: Path,
    *,
    nodeids: tuple[str, ...] = (),
    effective_after: str | None = None,
) -> Path:
    lines = [
        "# Reproducible-flake baseline for tests.",
        "# Entries are debt to remove.",
    ]
    if effective_after is not None:
        lines.append(f"# effective-after: {effective_after}")
    lines.extend(nodeids)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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


def test_fail_on_new_flake_passes_when_store_has_too_few_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    baseline = _baseline(tmp_path / "baseline.txt")
    tool = _load_tool()

    assert (
        tool.main(
            [
                "--store",
                str(store),
                "--flake-baseline",
                str(baseline),
                "--fail-on-new-flake",
            ]
        )
        == 0
    )

    assert "not enough full-lane records to judge" in capsys.readouterr().out


def test_fail_on_new_flake_reports_nodes_that_exceed_the_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    _write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    _write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = _baseline(tmp_path / "baseline.txt")
    tool = _load_tool()

    assert (
        tool.main(
            [
                "--store",
                str(store),
                "--flake-baseline",
                str(baseline),
                "--fail-on-new-flake",
            ]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "1 reproducible flake(s) exceed" in output
    assert FLAKE_NODE in output


def test_fail_on_new_flake_allows_committed_baseline_debt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    _write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    _write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = _baseline(tmp_path / "baseline.txt", nodeids=(FLAKE_NODE,))
    tool = _load_tool()

    assert (
        tool.main(
            [
                "--store",
                str(store),
                "--flake-baseline",
                str(baseline),
                "--fail-on-new-flake",
            ]
        )
        == 0
    )

    assert "no new reproducible flakes" in capsys.readouterr().out


def test_fail_on_new_flake_ignores_records_before_the_baseline_effective_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    _write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    _write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = _baseline(
        tmp_path / "baseline.txt",
        effective_after=(NOW + timedelta(minutes=4)).isoformat(),
    )
    tool = _load_tool()

    assert (
        tool.main(
            [
                "--store",
                str(store),
                "--flake-baseline",
                str(baseline),
                "--fail-on-new-flake",
            ]
        )
        == 0
    )

    assert "not enough full-lane records to judge" in capsys.readouterr().out


def test_fail_on_new_flake_ignores_fixed_deterministic_breaks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    _write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    _write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/fix.py"],
        failures=[],
    )
    baseline = _baseline(tmp_path / "baseline.txt")
    tool = _load_tool()

    assert (
        tool.main(
            [
                "--store",
                str(store),
                "--flake-baseline",
                str(baseline),
                "--fail-on-new-flake",
            ]
        )
        == 0
    )

    assert "no new reproducible flakes" in capsys.readouterr().out
