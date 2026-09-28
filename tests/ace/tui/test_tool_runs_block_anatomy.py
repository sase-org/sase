"""Tests for the runs-card-anatomy phase (epic sase-1bt, sase-1bt.7).

Full ``⚒ Runs`` block anatomy: outcome and context lines, the stage
waterfall, triage items with witness counts, child runs, the bounded
log tail, three detail levels, retention-honest absence, the
``tool_run_detail`` adapter, and the detail-loader LRU.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.tool_runs.blocks import (
    COMPACT_MAX_ITEMS,
    STANDARD_MAX_ITEMS,
    render_tool_run_block,
)
from sase.ace.tui.tool_runs.deck import ToolRunsDetailLevel
from sase.ace.tui.tool_runs import detail as _detail_module
from sase.ace.tui.tool_runs.detail import (
    _detail_lru_key,
    cached_tool_run_detail,
    load_tool_run_detail_blocking,
)
from sase.ace.tui.tool_runs.hints import (
    _run_log_hint_label,
    _tool_run_log_hint_target,
    hint_number_for_tool_run,
    run_id_from_hint_target,
    visible_tool_run_log_targets,
)
from sase.ace.tui.tool_runs.waterfall import (
    WATERFALL_NARROW_WIDTH,
    waterfall_rows,
)
from sase.core.tool_run import (
    ToolRunBrief,
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
    ToolRunDetailTriageItem,
    ToolRunExpectedStage,
    ToolRunLogMetadata,
    ToolRunVerdictSummary,
)


def _verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        unknown=int(counts.get("unknown", 0)),
    )


def _brief(
    run_id: str = "6c3d5107" + "0" * 24,
    label: str = "check",
    bucket: str = "new_failures",
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state="succeeded",
        created_ts=1000,
        verdict=_verdict(bucket, **counts),
        tool_name="check",
        agent="0t9--code",
        bead="sase-1b2.20",
        workspace="13",
        settled_ts=1752,
        duration_ms=252000,
        typical_ms=253000,
    )


def _stage(
    description: str,
    started_ms: int | None = 0,
    elapsed_ms: int | None = 1000,
    exit_code: int | None = 0,
    **counts: Any,
) -> ToolRunDetailStage:
    finished = (
        None
        if started_ms is None
        else (None if elapsed_ms is None else started_ms + elapsed_ms)
    )
    return ToolRunDetailStage(
        description=description,
        started_ms=started_ms,
        finished_ms=finished,
        elapsed_ms=elapsed_ms,
        exit_code=exit_code,
        counts=ToolRunDetailStageCounts(
            new=int(counts.get("new", 0)),
            known=int(counts.get("known", 0)),
        ),
    )


def _item(
    display: str,
    item_class: str | None = "NEW",
    stage_key: str = "lint (mypy)",
) -> ToolRunDetailTriageItem:
    return ToolRunDetailTriageItem(
        stage_key=stage_key,
        display=display,
        occurrences=3,
        witness_runs=35,
        witness_agents=33,
        item_class=item_class,
        first_seen_ts=1758600000,
    )


def _detail(**overrides: Any) -> ToolRunDetail:
    kwargs: dict[str, Any] = {
        "store_exists": True,
        "found": True,
        "display_argv": ("just", "check"),
        "stages": (
            _stage("fmt (python)", 0, 300),
            _stage("lint (mypy)", 300, 63000),
        ),
        "triage_items": (_item('_tree.py:622 Name "prefix_key" already defined'),),
    }
    kwargs.update(overrides)
    return ToolRunDetail(**kwargs)


def _tail(lines: int = 12, **kwargs: Any) -> SimpleNamespace:
    params: dict[str, Any] = {
        "availability": "available",
        "source": "run",
        "lines": tuple(f"line {index}" for index in range(lines)),
        "total_bytes": 1200,
        "truncated": False,
    }
    params.update(kwargs)
    return SimpleNamespace(**params)


def setup_function(_: object) -> None:
    with _detail_module._detail_lock:
        _detail_module._detail_lru.clear()


def test_new_failures_block_anatomy() -> None:
    text = render_tool_run_block(_brief(new=3, known=1), _detail(), tail=_tail()).plain
    assert "⚒ check" in text
    assert "3 NEW · 1 KNOWN" in text
    assert "run 6c3d5107 · inline · turn 0t9--code · bead sase-1b2.20 · ws 13" in text
    assert "$ just check" in text
    assert "fmt (python)" in text
    assert "lint (mypy)" in text
    assert "NEW" in text
    assert "35 runs · 33 agents" in text
    assert "log tail" in text
    assert "line 0" in text


def test_known_only_block() -> None:
    brief = _brief(bucket="known_only", known=2)
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "known only · 2 KNOWN" in text


def test_undetermined_unknown_block() -> None:
    brief = _brief(bucket="undetermined", unknown=2)
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "2 UNKNOWN" in text


def test_undetermined_untriaged_block() -> None:
    brief = _brief(bucket="undetermined")
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "untriaged" in text


def test_pass_block() -> None:
    brief = _brief(bucket="pass")
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "pass" in text


def test_killed_block_has_explanation_line() -> None:
    brief = ToolRunBrief(
        run_id="a" * 32,
        label="check",
        state="killed",
        created_ts=1000,
        verdict=_verdict("killed"),
        terminal_cause="signal",
        duration_ms=540000,
    )
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "killed at 9m00s · signal" in text
    assert "the caller killed the command; this is not a test failure" in text


def test_stopped_block() -> None:
    brief = ToolRunBrief(
        run_id="b" * 32,
        label="check",
        state="stopped",
        created_ts=1000,
        verdict=_verdict("stopped"),
        terminal_cause="stop_requested",
        duration_ms=62000,
    )
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "stopped at 1m02s" in text
    assert "this is not a test failure" not in text


def test_lost_block() -> None:
    brief = ToolRunBrief(
        run_id="c" * 32,
        label="check",
        state="lost",
        created_ts=1000,
        verdict=_verdict("lost"),
        terminal_cause="wrapper_lost",
    )
    text = render_tool_run_block(brief, _detail(), tail=_tail()).plain
    assert "lost · wrapper_lost" in text


def test_pruned_detail_is_honest() -> None:
    detail = _detail(detail_pruned=True)
    text = render_tool_run_block(_brief(), detail, tail=_tail()).plain
    assert "detail pruned · summary retained" in text
    assert "fmt (python)" not in text


def test_missing_detail_is_honest() -> None:
    text = render_tool_run_block(_brief(), None).plain
    assert "run detail unavailable · summary retained" in text
    assert "⚒ check" in text


def test_pruned_log_is_honest() -> None:
    tail = _tail(0, availability="pruned", source="none")
    text = render_tool_run_block(_brief(), _detail(), tail=tail).plain
    assert "log pruned (retention)" in text
    assert "line 0" not in text


def test_owner_log_unavailable_is_honest() -> None:
    tail = _tail(0, availability="owner-missing", source="none")
    text = render_tool_run_block(_brief(), _detail(), tail=tail).plain
    assert "owner log unavailable" in text


def test_no_log_recorded_is_honest() -> None:
    text = render_tool_run_block(_brief(), _detail(), tail=None).plain
    assert "no log recorded" in text


def test_truncated_tail_header_states_counts() -> None:
    tail = _tail(12, total_bytes=1_200_000, truncated=True)
    text = render_tool_run_block(_brief(), _detail(), tail=tail).plain
    assert "12 lines" in text
    assert "1.2 MB" in text
    assert "truncated" in text


def test_child_runs_render_as_nested_lines() -> None:
    child = ToolRunBrief(
        run_id="81ef0cb1" + "0" * 24,
        label="test",
        state="succeeded",
        created_ts=1100,
        verdict=_verdict("pass"),
        duration_ms=62000,
    )
    text = render_tool_run_block(
        _brief(), _detail(child_runs=(child,)), tail=_tail()
    ).plain
    assert "↳ child run 81ef0cb1 test" in text


def test_compact_collapses_passed_stages() -> None:
    text = render_tool_run_block(
        _brief(),
        _detail(),
        tail=_tail(),
        level=ToolRunsDetailLevel.COMPACT,
    ).plain
    assert "✓ 2 stages passed" in text
    assert "fmt (python)" not in text
    assert "log tail" not in text


def test_compact_keeps_failing_stages() -> None:
    failing = _stage("lint (symvision)", 63300, 67000, exit_code=1, new=2)
    detail = _detail(stages=(_stage("fmt (python)", 0, 300), failing))
    text = render_tool_run_block(
        _brief(), detail, tail=_tail(), level=ToolRunsDetailLevel.COMPACT
    ).plain
    assert "lint (symvision)" in text
    assert "2 NEW" in text


def test_compact_top_three_items() -> None:
    items = tuple(_item(f"failure {index}") for index in range(6))
    detail = _detail(triage_items=items)
    text = render_tool_run_block(
        _brief(), detail, tail=_tail(), level=ToolRunsDetailLevel.COMPACT
    ).plain
    assert "failure 0" in text
    assert "failure 2" in text
    assert "failure 3" not in text
    assert f"+{len(items) - COMPACT_MAX_ITEMS} more" in text


def test_standard_caps_items_at_twenty() -> None:
    items = tuple(_item(f"failure {index}") for index in range(25))
    detail = _detail(triage_items=items)
    text = render_tool_run_block(_brief(), detail, tail=_tail()).plain
    assert "failure 19" in text
    assert "failure 20" not in text
    assert f"+{len(items) - STANDARD_MAX_ITEMS} more" in text


def test_full_shows_locator_paths_and_sixty_line_tail() -> None:
    item = ToolRunDetailTriageItem(
        stage_key="lint (mypy)",
        display="boom",
        occurrences=1,
        witness_runs=2,
        witness_agents=2,
        item_class="NEW",
        locator_paths=("src/a.py", "src/b.py"),
    )
    tail = _tail(60)
    text = render_tool_run_block(
        _brief(),
        _detail(triage_items=(item,)),
        tail=tail,
        level=ToolRunsDetailLevel.FULL,
    ).plain
    assert "src/a.py" in text
    assert "line 59" in text


def test_display_argv_only_never_private() -> None:
    detail = _detail()
    sneaky = SimpleNamespace(
        **{**detail.__dict__, "private_argv": ("s3cr3t-token",)},
    )
    text = render_tool_run_block(_brief(), sneaky, tail=_tail()).plain
    assert "$ just check" in text
    assert "s3cr3t-token" not in text


def test_waterfall_offsets_and_lengths() -> None:
    import re

    stages = (
        _stage("first", 0, 10_000),
        _stage("second", 10_000, 30_000),
    )
    rows = waterfall_rows(stages, width=100).plain.splitlines()
    assert len(rows) == 2
    first_bar = re.search(r"10s( +)([█▏▎▍▌▋▊▉]+)", rows[0])
    second_bar = re.search(r"30s( +)([█▏▎▍▌▋▊▉]+)", rows[1])
    assert first_bar is not None and second_bar is not None
    assert first_bar.group(1) == "  "
    assert len(second_bar.group(1)) > len(first_bar.group(1))
    assert len(second_bar.group(2)) > len(first_bar.group(2))


def test_waterfall_minimum_one_cell() -> None:
    stages = (_stage("tiny", 0, 1, exit_code=0), _stage("huge", 1, 3_600_000))
    lines = waterfall_rows(stages, width=100).plain.splitlines()
    assert len(lines) == 2
    assert "█" in lines[0] or "▏" in lines[0]


def test_waterfall_narrow_fallback_keeps_table() -> None:
    stages = (_stage("fmt", 0, 300),)
    text = waterfall_rows(stages, width=WATERFALL_NARROW_WIDTH - 1).plain
    assert "fmt" in text
    assert "█" not in text and "▏" not in text and "▌" not in text


def test_waterfall_pending_and_not_reached() -> None:
    expected = (ToolRunExpectedStage("test (scoped)", 91000),)
    live = waterfall_rows((), expected, width=100, is_live=True).plain
    assert "typ 1m 31s" in live
    settled = waterfall_rows((), expected, width=100, is_live=False).plain
    assert "not reached" in settled


def test_detail_adapter_from_wire() -> None:
    wire = {
        "schema_version": 1,
        "store_exists": True,
        "found": True,
        "display_argv": ["just", "check"],
        "stages": [
            {
                "description": "lint",
                "started_ms": 100,
                "finished_ms": 200,
                "elapsed_ms": 100,
                "exit_code": 1,
                "incomplete": False,
                "counts": {"new": 2, "known": 1, "flaky": 0, "unknown": 0},
            }
        ],
        "expected_stages": [{"description": "test", "elapsed_ms": 500}],
        "triage_items": [
            {
                "class": "NEW",
                "stage_key": "lint",
                "display": "boom",
                "locator_paths": ["a.py"],
                "occurrences": 1,
                "witness_runs": 4,
                "witness_agents": 3,
                "first_seen_ts": 10,
                "last_seen_ts": 20,
            }
        ],
        "items_truncated": False,
        "child_runs": [],
        "logs": {"stdout_path": "/tmp/out.log", "has_private_argv": False},
        "detail_pruned": False,
        "diagnostics": [],
        "brief": {
            "run_id": "d" * 32,
            "label": "check",
            "state": "failed",
            "created_ts": 1,
        },
        "mystery_future_key": "ignored",
    }
    detail = ToolRunDetail.from_wire(wire)
    assert detail.found
    assert detail.display_argv == ("just", "check")
    assert detail.stages[0].exit_code == 1
    assert detail.stages[0].counts.new == 2
    assert detail.expected_stages[0].description == "test"
    assert detail.triage_items[0].item_class == "NEW"
    assert detail.triage_items[0].locator_paths == ("a.py",)
    assert detail.logs.stdout_path == "/tmp/out.log"
    assert detail.brief is not None and detail.brief.run_id == "d" * 32


def test_detail_lru_key_shapes() -> None:
    live = SimpleNamespace(state="running", settled_ts=None)
    assert _detail_lru_key("abc", live, "tok") == ("abc", "live", "tok")
    settled = SimpleNamespace(state="succeeded", settled_ts=1752)
    assert _detail_lru_key("abc", settled, "tok") == ("abc", "1752")


def test_detail_lru_hits_settled_run_without_io(monkeypatch: Any) -> None:
    calls: list[str] = []

    def _fake_detail(run_id: str, **kwargs: Any) -> ToolRunDetail:
        calls.append(run_id)
        return _detail()

    def _fake_tail(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return _tail(0)

    import sase.ace.tui.tool_runs.detail as detail_module

    monkeypatch.setattr(detail_module, "tool_run_detail", _fake_detail)
    import sase.tool.logs as logs_module

    monkeypatch.setattr(logs_module, "tool_run_log_tail", _fake_tail)
    brief = _brief()
    first = load_tool_run_detail_blocking(brief.run_id, brief, "tok")
    assert first is not None
    assert calls == [brief.run_id]
    second = load_tool_run_detail_blocking(brief.run_id, brief, "tok")
    assert second is first
    assert calls == [brief.run_id]
    assert cached_tool_run_detail(brief.run_id, brief, "tok") is first


def test_detail_loader_failure_returns_none(monkeypatch: Any) -> None:
    import sase.ace.tui.tool_runs.detail as detail_module

    def _boom(run_id: str, **kwargs: Any) -> ToolRunDetail:
        raise RuntimeError("store locked")

    monkeypatch.setattr(detail_module, "tool_run_detail", _boom)
    assert load_tool_run_detail_blocking("e" * 32) is None


def test_hint_target_round_trip() -> None:
    run_id = "6c3d5107" + "0" * 24
    target = _tool_run_log_hint_target(run_id)
    assert target == f"toolrun-log:{run_id}"
    assert run_id_from_hint_target(target or "") == run_id
    assert run_id_from_hint_target("/tmp/x.log") is None
    assert _run_log_hint_label(run_id) == "⚒ run log 6c3d5107"
    assert _tool_run_log_hint_target("") is None


def test_visible_targets_follow_block_order() -> None:
    blocks = [
        SimpleNamespace(block_id="a" * 32),
        SimpleNamespace(block_id="b" * 32),
        SimpleNamespace(block_id="a" * 32),
    ]
    assert visible_tool_run_log_targets(blocks) == [
        ("⚒ run log " + "a" * 8, f"toolrun-log:{'a' * 32}"),
        ("⚒ run log " + "b" * 8, f"toolrun-log:{'b' * 32}"),
    ]


def test_hint_number_lookup() -> None:
    run_id = "c" * 32
    mappings = {1: "/tmp/a.py", 2: f"toolrun-log:{run_id}"}
    assert hint_number_for_tool_run(mappings, run_id) == 2
    assert hint_number_for_tool_run(mappings, "d" * 32) is None


def test_tail_header_shows_hint_marker() -> None:
    text = render_tool_run_block(
        _brief(),
        _detail(),
        tail=_tail(),
        hint_numbers={_brief().run_id: 7},
    ).plain
    assert "[7] ⚒ run log" in text
