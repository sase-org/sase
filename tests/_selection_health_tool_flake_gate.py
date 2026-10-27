"""Flake-gate behavior for the selection-health tool."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests._selection_health_tool_helpers import (
    AUDIT_NODE,
    FLAKE_NODE,
    NOW,
    ROOT,
    write_baseline,
    load_tool,
    write_full_run,
)


def test_fail_on_new_flake_passes_when_store_has_too_few_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    baseline = write_baseline(tmp_path / "baseline.txt")
    tool = load_tool()

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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = write_baseline(tmp_path / "baseline.txt")
    tool = load_tool()
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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = write_baseline(tmp_path / "baseline.txt")
    tool = load_tool()
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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = write_baseline(tmp_path / "baseline.txt", nodeids=(FLAKE_NODE,))
    tool = load_tool()

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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    baseline = write_baseline(
        tmp_path / "baseline.txt",
        effective_after=(NOW + timedelta(minutes=4)).isoformat(),
    )
    tool = load_tool()

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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/a.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/b.py"],
        failures=[FLAKE_NODE],
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/fix.py"],
        failures=[],
    )
    baseline = write_baseline(tmp_path / "baseline.txt")
    tool = load_tool()

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
    write_full_run(
        store,
        minute=1,
        changed_files=["src/sase/monitor/supervise.py"],
        failures=[AUDIT_NODE],
        tree_dirty=True,
    )
    write_full_run(
        store,
        minute=2,
        changed_files=["src/sase/pass.py"],
        failures=[],
        tree_dirty=False,
    )
    write_full_run(
        store,
        minute=3,
        changed_files=["src/sase/ace/tui/models/_loaders/_workflow_loaders.py"],
        failures=[AUDIT_NODE],
        tree_dirty=True,
    )
    baseline = write_baseline(tmp_path / "baseline.txt")
    tool = load_tool()

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


def test_committed_flake_baseline_parses_through_the_tool_parser() -> None:
    # sase-1og: the committed baseline once held two `# fixed-at:` directives
    # for the same node, which made the `check-full` flake-baseline gate exit
    # 2 on every run. Loading it here through the tool's own parser keeps that
    # class of debt failing `just check` instead of only `check-full`.
    tool = load_tool()
    baseline = tool.load_flake_baseline(
        ROOT / "tests" / "reproducible_flake_baseline.txt"
    )
    assert baseline.nodeids, "committed flake baseline must not be empty"
    assert baseline.effective_after is not None
