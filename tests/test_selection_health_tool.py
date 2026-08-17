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
AUDIT_NODE = (
    "tests/test_agent_artifact_marker_path_passing_audit.py"
    "::test_tracked_marker_path_passing_sites_are_reviewed"
)


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
    tree_dirty: bool | None = None,
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
            tree_dirty=tree_dirty,
            now=when,
        ),
    )


def _baseline(
    path: Path,
    *,
    nodeids: tuple[str, ...] = (),
    effective_after: str | None = None,
    retirements: tuple[tuple[str, str], ...] = (),
) -> Path:
    lines = [
        "# Reproducible-flake baseline for tests.",
        "# Entries are debt to remove.",
    ]
    if effective_after is not None:
        lines.append(f"# effective-after: {effective_after}")
    lines.extend(
        f"# fixed-at: {timestamp} {nodeid}" for timestamp, nodeid in retirements
    )
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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
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
    # FLAKE_NODE names no real file on disk; the default oracle checks the
    # real repo, so a test asking about the baseline gate's own logic must
    # supply one that treats it as still collectable.
    monkeypatch.setattr(
        tool, "collectible_nodeid_oracle", lambda _root: lambda _nodeid: True
    )

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


def test_fail_on_new_flake_treats_an_uncollectable_node_as_stale_not_a_flake(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A renamed or deleted test's old node ID can never pass again, so
    # without a staleness check it would be gated as a live flake forever.
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
    monkeypatch.setattr(
        tool, "collectible_nodeid_oracle", lambda _root: lambda _nodeid: False
    )

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

    output = capsys.readouterr().out
    assert "no new reproducible flakes" in output
    assert "no longer collectable" in output
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


def test_fail_on_new_flake_excludes_attributable_dirty_tree_audit_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # sase-lc: a source-tree audit failing twice, from unrelated workspaces,
    # each time recorded dirty with an uncommitted change under the audit's
    # own scanned root (src/sase/). Without the attribution rule this shape
    # is exactly what made the node read as a reproducible flake.
    store = tmp_path / "store"
    _write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/monitor/supervise.py"],
        failures=[AUDIT_NODE],
        tree_dirty=True,
    )
    _write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
        tree_dirty=False,
    )
    _write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/ace/tui/models/_loaders/_workflow_loaders.py"],
        failures=[AUDIT_NODE],
        tree_dirty=True,
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

    output = capsys.readouterr().out
    assert "no new reproducible flakes" in output
    assert "excluded from flake evidence as attributable dirty-tree" in output
    assert AUDIT_NODE in output


def _wfr(store: Path, minute: int, changed: list[str], failures: list[str]) -> None:
    _write_full_run(store, minute=minute, changed_files=changed, failures=failures)


def _write_flake_pattern(
    store: Path, node: str, *, start_minute: int, tag: str
) -> None:
    """Write the fail/pass/fail pattern that alone meets the flake evidence bar."""
    _wfr(store, start_minute, [f"src/sase/{tag}1.py"], [node])
    _wfr(store, start_minute + 1, [f"src/sase/{tag}p.py"], [])
    _wfr(store, start_minute + 2, [f"src/sase/{tag}2.py"], [node])


def _gate_argv(store: Path, baseline: Path) -> list[str]:
    return [
        "--store",
        str(store),
        "--flake-baseline",
        str(baseline),
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
    baseline = _baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = _load_tool()
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
        _write_full_run(store, minute=minute, changed_files=changed, failures=failures)
    fixed_at = (NOW + timedelta(minutes=2)).isoformat()
    baseline = _baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = _load_tool()
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
    baseline = _baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = _load_tool()
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
    baseline = _baseline(
        tmp_path / "b.txt", nodeids=(FLAKE_NODE,), retirements=((fixed_at, FLAKE_NODE),)
    )
    tool = _load_tool()

    assert tool.main(_gate_argv(store, baseline)) == 0

    output = capsys.readouterr().out
    assert "no new reproducible flakes" in output
    assert "retired nothing in the current window and can be removed" in output
    assert FLAKE_NODE in output


def test_fail_on_new_flake_exits_2_on_malformed_fixed_at_directives(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
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
    tool = _load_tool()
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
    baseline = _baseline(tmp_path / "b.txt", retirements=((fixed_at, FLAKE_NODE),))
    tool = _load_tool()
    _patch_collectible_true(tool, monkeypatch)

    assert tool.main(_gate_argv(store, baseline)) == 1

    output = capsys.readouterr().out
    assert "1 reproducible flake(s) exceed" in output
    assert FLAKE_NODE in output
