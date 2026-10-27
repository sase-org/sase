"""Fixed-at retirement behavior for the selection-health tool."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest

from tests._selection_health_tool_helpers import (
    FLAKE_NODE,
    NOW,
    WORKSPACE,
    write_baseline,
    load_tool,
    write_full_run,
)
from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    write_record,
)


def _write_flake_pattern(
    store: Path, node: str, *, start_minute: int, tag: str
) -> None:
    """Write the fail/pass/fail pattern that alone meets the flake evidence bar."""
    write_full_run(
        store,
        minute=start_minute,
        changed_files=[f"src/sase/{tag}1.py"],
        failures=[node],
    )
    write_full_run(
        store,
        minute=start_minute + 1,
        changed_files=[f"src/sase/{tag}p.py"],
        failures=[],
    )
    write_full_run(
        store,
        minute=start_minute + 2,
        changed_files=[f"src/sase/{tag}2.py"],
        failures=[node],
    )


def _gate_argv(store: Path, baseline_path: Path) -> list[str]:
    return [
        "--store",
        str(store),
        "--flake-baseline",
        str(baseline_path),
        "--fail-on-new-flake",
    ]


def _patch_collectible_true(tool: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # A synthetic node name no real file backs; treat every node as collectable.
    monkeypatch.setattr(
        tool, "collectible_nodeid_oracle", lambda _root: lambda _n: True
    )


def test_fail_on_new_flake_retires_evidence_recorded_before_the_fix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    _write_flake_pattern(store, FLAKE_NODE, start_minute=1, tag="a")
    fixed_at = (NOW + timedelta(minutes=4)).isoformat()
    baseline = write_baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = load_tool()
    _patch_collectible_true(tool, monkeypatch)

    assert tool.main(_gate_argv(store, baseline)) == 0

    output = capsys.readouterr().out
    assert "no new reproducible flakes" in output
    assert "retired by a # fixed-at:" in output
    assert FLAKE_NODE in output


def test_fail_on_new_flake_still_flags_a_node_that_fails_again_after_its_fix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only the failures at or before `fixed-at` are retired; later ones stay live.
    store = tmp_path / "store"
    for minute, changed, failures in [
        (1, ["src/sase/a.py"], [FLAKE_NODE]),
        (2, ["src/sase/p1.py"], []),
        (3, ["src/sase/b.py"], [FLAKE_NODE]),
        (4, ["src/sase/p2.py"], []),
        (5, ["src/sase/c.py"], [FLAKE_NODE]),
    ]:
        write_full_run(store, minute=minute, changed_files=changed, failures=failures)
    fixed_at = (NOW + timedelta(minutes=2)).isoformat()
    baseline = write_baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = load_tool()
    _patch_collectible_true(tool, monkeypatch)

    assert tool.main(_gate_argv(store, baseline)) == 1

    output = capsys.readouterr().out
    assert "1 reproducible flake(s) exceed" in output
    assert FLAKE_NODE in output


def test_fail_on_new_flake_retirement_is_scoped_to_its_own_node(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_node = "tests/test_other_flaky.py::test_y"
    store = tmp_path / "store"
    _write_flake_pattern(store, FLAKE_NODE, start_minute=1, tag="a")
    _write_flake_pattern(store, other_node, start_minute=4, tag="b")
    fixed_at = (NOW + timedelta(minutes=4)).isoformat()
    baseline = write_baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = load_tool()
    _patch_collectible_true(tool, monkeypatch)

    assert tool.main(_gate_argv(store, baseline)) == 1

    output = capsys.readouterr().out
    # The retirement diagnostic still names the retired node, so split it off first.
    flake_section, _, diagnostics_section = output.partition(
        "Additions require a filed bead"
    )
    assert other_node in flake_section
    assert FLAKE_NODE not in flake_section
    assert f"{FLAKE_NODE} (" in diagnostics_section


def test_fail_on_new_flake_reports_a_fixed_at_entry_that_retired_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _write_flake_pattern(store, FLAKE_NODE, start_minute=1, tag="a")
    # A fix instant before every recorded failure retires none of them.
    fixed_at = (NOW - timedelta(days=1)).isoformat()
    baseline = write_baseline(
        tmp_path / "b.txt", nodeids=(FLAKE_NODE,), retirements=((fixed_at, FLAKE_NODE),)
    )
    tool = load_tool()

    assert tool.main(_gate_argv(store, baseline)) == 0

    output = capsys.readouterr().out
    assert "no new reproducible flakes" in output
    assert "retired nothing in the current window and can be removed" in output
    assert FLAKE_NODE in output


def test_fail_on_new_flake_exits_2_on_malformed_fixed_at_directives(
    tmp_path: Path,
) -> None:
    tool = load_tool()
    store = tmp_path / "store"
    bad_directives = (
        "# fixed-at: not-a-timestamp tests/test_x.py::test_y\n",
        "# fixed-at: 2026-08-16T23:02:36Z\n",
    )
    for index, text in enumerate(bad_directives):
        baseline = tmp_path / f"bad-{index}.txt"
        baseline.write_text(text, encoding="utf-8")
        assert tool.main(_gate_argv(store, baseline)) == 2


def test_fail_on_new_flake_exits_2_on_a_duplicate_fixed_at_entry(
    tmp_path: Path,
) -> None:
    tool = load_tool()
    store = tmp_path / "store"
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(
        "# fixed-at: 2026-08-16T23:02:36Z tests/test_x.py::test_y\n"
        "# fixed-at: 2026-08-17T00:00:00Z tests/test_x.py::test_y\n",
        encoding="utf-8",
    )

    assert tool.main(_gate_argv(store, baseline)) == 2


def test_fail_on_new_flake_does_not_retire_a_record_with_no_recorded_at(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unreadable `recorded_at` must keep its evidence, fail-closed.
    store = tmp_path / "store"

    def _write(
        minute: int, changed: list[str], failures: list[str], recorded_at: str | None
    ) -> None:
        when = NOW + timedelta(minutes=minute)
        path = allocate_record_path(
            store, KIND_FULL_RUN, head=f"h{minute}", pid=minute, now=when
        )
        record = full_run_record(
            head=f"h{minute}",
            mode="fast",
            failures=failures,
            exit_status=1,
            workspace=WORKSPACE,
            changed_files=changed,
            now=when,
        )
        record["recorded_at"] = recorded_at
        write_record(path, record)

    _write(1, ["src/sase/a.py"], [FLAKE_NODE], None)
    _write(2, ["src/sase/p.py"], [], (NOW + timedelta(minutes=2)).isoformat())
    _write(3, ["src/sase/b.py"], [FLAKE_NODE], (NOW + timedelta(minutes=3)).isoformat())
    # Positioned to retire minute=1 if its timestamp were readable.
    fixed_at = (NOW + timedelta(minutes=1, seconds=30)).isoformat()
    baseline = write_baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = load_tool()
    _patch_collectible_true(tool, monkeypatch)

    assert tool.main(_gate_argv(store, baseline)) == 1

    output = capsys.readouterr().out
    assert "1 reproducible flake(s) exceed" in output
    assert FLAKE_NODE in output
