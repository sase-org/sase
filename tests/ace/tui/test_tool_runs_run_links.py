"""Tests for the run-links phase (epic sase-1bt, sase-1bt.9, plan §3.9)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.llm_calls._entry import ToolCallEntry
from sase.ace.tui.tool_runs import links as run_links
from sase.ace.tui.widgets._llm_calls_panel_timeline import (
    build_llm_calls_timeline_markdown,
    build_llm_calls_timeline_text,
)
from sase.core.tool_run import ToolRunBrief, ToolRunGlance, ToolRunVerdictSummary

_NOW_TS = 1_700_000_000.0


def _verdict(bucket: str, **counts: object) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),  # type: ignore[arg-type]
        known=int(counts.get("known", 0)),  # type: ignore[arg-type]
        unknown=int(counts.get("unknown", 0)),  # type: ignore[arg-type]
        reasons=tuple(counts.get("reasons", ())),  # type: ignore[arg-type]
    )


def _brief(
    run_id: str,
    *,
    label: str = "check",
    bucket: str = "pass",
    created_ts: int = 1_700_000_000,
    tool_name: str | None = "check",
    agent: str | None = "0t9--code",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    **counts: object,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state="succeeded",
        created_ts=created_ts,
        verdict=_verdict(bucket, **counts),
        tool_name=tool_name,
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
    )


def _glance(
    run_id: str,
    *,
    label: str = "check",
    created_ts: int = 1_699_999_900,
    tool_name: str | None = "check",
    agent: str | None = "0t9--code",
    stages_done: int = 6,
    stages_expected: int | None = 11,
) -> ToolRunGlance:
    return ToolRunGlance(
        run_id=run_id,
        label=label,
        state="running",
        created_ts=created_ts,
        last_activity_ts=1_699_999_990,
        stages_done=stages_done,
        stages_expected=stages_expected,
        tool_name=tool_name,
        agent=agent,
        running_ts=created_ts,
    )


def _bash_entry(
    command: str,
    *,
    recorded_at: str = "2023-11-14T22:13:19Z",
    duration_ms: int | None = 120_000,
    output: str = "",
    tool_use_id: str | None = None,
    line_number: int = 7,
) -> ToolCallEntry:
    return ToolCallEntry(
        recorded_at=recorded_at,
        runtime="codex",
        event="ToolCall",
        status="success",
        tool_name="Bash",
        tool_use_id=tool_use_id,
        duration_ms=duration_ms,
        tool_input_summary={"command": command},
        tool_response_summary={"output_preview": output} if output else {},
        line_number=line_number,
        _recorded_at_sort=datetime(2023, 11, 14, 22, 13, 19, tzinfo=UTC),
    )


def test_join_exact_argv_and_window() -> None:
    run = _brief("a" * 32, bucket="new_failures", new=3, known=1)
    entry = _bash_entry(
        "sase tool run check",
        recorded_at="2023-11-14T22:13:19Z",
        duration_ms=120_000,
    )
    # created_ts 1_699_999_900 == recorded start; inside the window.
    assert run_links.match_llm_call_to_run(entry, (run,)) is run


def test_join_window_edges_reject() -> None:
    entry = _bash_entry("sase tool run check")
    early = _brief("b" * 32, created_ts=1_699_999_990)
    late = _brief("c" * 32, created_ts=1_700_000_130)
    assert run_links.match_llm_call_to_run(entry, (early,)) is None
    assert run_links.match_llm_call_to_run(entry, (late,)) is None


def test_join_nearest_wins_with_two_runs_in_window() -> None:
    near = _brief("d" * 32, created_ts=1_700_000_050)
    far = _brief("e" * 32, created_ts=1_700_000_000)
    entry = _bash_entry("sase tool run check")
    assert run_links.match_llm_call_to_run(entry, (far, near)) is near


def test_join_scrape_only_without_time_match() -> None:
    run_id = "f" * 32
    run = _brief(run_id, created_ts=1_699_990_000)
    entry = _bash_entry(
        "sase tool run check",
        output=f"done\nsase tool show {run_id} -l\n",
    )
    assert run_links.match_llm_call_to_run(entry, (run,)) is run


def test_non_tool_bash_row_gets_no_suffix() -> None:
    run = _brief("a" * 32)
    entry = _bash_entry("ls -la /tmp")
    assert run_links.match_llm_call_to_run(entry, (run,)) is None
    fetch_time = datetime(2023, 11, 14, 22, 14, 0, tzinfo=UTC)
    links = run_links.match_llm_calls_to_runs((entry,), (run,))
    assert links == {}
    text = build_llm_calls_timeline_text(
        (entry,), fetch_time, run_links=links, now_ts=_NOW_TS
    )
    assert "⚒" not in text.plain
    markdown = build_llm_calls_timeline_markdown(
        (entry,), fetch_time, run_links=links, now_ts=_NOW_TS
    )
    assert markdown is not None and "⚒" not in markdown


def test_suffix_in_both_twins() -> None:
    run = _brief("ab12" * 8, bucket="new_failures", new=3, known=1)
    entry = _bash_entry("sase tool run check")
    links = {id(entry): run}
    fetch_time = datetime(2023, 11, 14, 22, 14, 0, tzinfo=UTC)
    text = build_llm_calls_timeline_text(
        (entry,), fetch_time, run_links=links, now_ts=_NOW_TS
    )
    assert "→ ⚒ check ✗ 3 NEW" in text.plain
    markdown = build_llm_calls_timeline_markdown(
        (entry,), fetch_time, run_links=links, now_ts=_NOW_TS
    )
    assert markdown is not None and "→ ⚒ check ✗ 3 NEW" in markdown


def test_jump_target_round_trip_and_hint_label() -> None:
    run_id = "ab12cd34" * 4
    target = run_links.tool_run_jump_target(run_id)
    assert target is not None
    assert run_links.run_id_from_jump_target(target) == run_id
    assert run_links.run_jump_hint_label(run_id) == f"⚒ run {run_id[:8]}"
    pairs = run_links.visible_tool_run_jump_targets((SimpleNamespace(run_id=run_id),))
    assert pairs == [(f"⚒ run {run_id[:8]}", target)]


def test_slow_tool_suffix_running_and_settled() -> None:
    live = _glance("11" * 16, stages_done=6, stages_expected=11)
    settled = _brief("22" * 16, bucket="new_failures", new=3, known=1)
    assert run_links.slow_tool_run_suffix_text(live, now_ts=_NOW_TS) == (
        "· ⚒ check 7/11"
    )
    assert "✗ 3 NEW" in run_links.slow_tool_run_suffix_text(settled, now_ts=_NOW_TS)


def test_monitor_context_row_from_ledger_owner_join() -> None:
    run = _brief(
        "ab12cd34" * 4,
        bucket="new_failures",
        new=3,
        known=1,
        agent="starter-turn",
        owner_kind="monitor",
        owner_id="mon-1",
    )
    summary = SimpleNamespace(latest_by_tool=(run,), runs=(run,))
    agent = SimpleNamespace(
        is_monitor=True,
        monitor_id="mon-1",
        is_named_proc=False,
        proc_id=None,
        agent_name=None,
        display_name=None,
        fleet_origin_alias=None,
        is_clan_container=False,
        is_session_container=False,
        session_member_names=(),
        container_name=None,
        start_time=None,
    )
    row = run_links.context_row_for_agent(agent, summary, now_ts=_NOW_TS)
    assert row is not None
    assert "⚒ check ✗ 3 NEW" in row.plain
    assert "ab12cd34" in row.plain


def test_non_tool_timeline_has_no_suffix() -> None:
    entry = _bash_entry("sase tool run check")
    fetch_time = datetime(2023, 11, 14, 22, 14, 0, tzinfo=UTC)
    plain = build_llm_calls_timeline_text((entry,), fetch_time)
    assert "⚒" not in plain.plain


def _node_agent(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "is_monitor": False,
        "monitor_id": None,
        "is_named_proc": False,
        "proc_id": None,
        "agent_name": "0t9--code",
        "display_name": None,
        "fleet_origin_alias": None,
        "is_clan_container": False,
        "is_session_container": False,
        "session_member_names": (),
        "container_name": None,
        "start_time": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_wiring_links_for_agent_entries() -> None:
    run = _brief("ab12" * 8, bucket="new_failures", new=3, known=1)
    summary = SimpleNamespace(latest_by_tool=(run,), runs=(run,))
    entry = _bash_entry("sase tool run check")
    links = run_links.run_links_for_agent_entries(
        _node_agent(), (entry,), summary, snapshot_runs=()
    )
    assert links == {id(entry): run}


def test_wiring_slow_suffixes_for_sources() -> None:
    run = _brief("ab12" * 8, bucket="new_failures", new=3, known=1)
    summary = SimpleNamespace(latest_by_tool=(run,), runs=(run,))
    entry = _bash_entry("sase tool run check")
    sources = (SimpleNamespace(entries=(entry,)),)
    suffixes = run_links.slow_suffixes_for_agent_sources(
        _node_agent(), sources, summary, snapshot_runs=()
    )
    assert set(suffixes) == {id(entry)}
    assert "· ⚒ check" in suffixes[id(entry)].plain


def test_wiring_context_row_cached() -> None:
    run = _brief("ab12cd34" * 4, bucket="new_failures", new=3, known=1)
    summary = SimpleNamespace(latest_by_tool=(run,), runs=(run,))
    row = run_links.context_row_for_agent_cached(
        _node_agent(), summary, snapshot_runs=()
    )
    assert row is not None
    assert "⚒ check ✗ 3 NEW" in row.plain
    assert "ab12cd34" in row.plain


def test_jump_meta_matches_block_header() -> None:
    from sase.ace.tui.tool_runs.deck import tool_run_block_header_text

    run = _brief("ab12cd34" * 4, bucket="new_failures", new=3, known=1)
    suffix = run_links.suffix_text_with_jump(run, prefix="→", now_ts=_NOW_TS)
    header = tool_run_block_header_text(0, run)
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        DECK_BLOCK_META_KEY,
    )

    def _meta_ids(text: object) -> set[str]:
        ids: set[str] = set()
        for span in getattr(text, "spans", ()):
            meta = getattr(span.style, "meta", None) if span.style else None
            if isinstance(meta, dict) and DECK_BLOCK_META_KEY in meta:
                ids.add(str(meta[DECK_BLOCK_META_KEY]))
        style = getattr(text, "style", None)
        meta = getattr(style, "meta", None) if style else None
        if isinstance(meta, dict) and DECK_BLOCK_META_KEY in meta:
            ids.add(str(meta[DECK_BLOCK_META_KEY]))
        return ids

    assert _meta_ids(suffix) == {"ab12cd34" * 4}
    assert _meta_ids(header) == {"ab12cd34" * 4}


def test_monitor_section_tool_run_row() -> None:
    from sase.ace.tui.models.agent import Agent
    from sase.ace.tui.models.agent_types import AgentType
    from sase.ace.tui.widgets.prompt_panel._agent_monitor_section import (
        build_monitor_section,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="",
        status="RUNNING",
        start_time=datetime(2026, 8, 20, 12, 0, 0),
        raw_suffix="mon1",
        agent_name="mon-agent",
        monitor_state="running",
        monitor_id="mon-1",
    )
    row = run_links.context_tool_run_line(
        _brief("ab12cd34" * 4, bucket="pass"), now_ts=_NOW_TS
    )
    with_row = Text()
    for part in build_monitor_section(agent, tool_run_row=row):
        if isinstance(part, Text):
            with_row.append_text(part)
    assert "Tool run:" in with_row.plain
    assert "⚒ check ✓" in with_row.plain
    without_row = Text()
    for part in build_monitor_section(agent):
        if isinstance(part, Text):
            without_row.append_text(part)
    assert "Tool run:" not in without_row.plain


def test_named_proc_section_tool_run_row() -> None:
    from sase.ace.tui.models.agent import Agent
    from sase.ace.tui.models.agent_types import AgentType
    from sase.ace.tui.widgets.prompt_panel._agent_named_proc_section import (
        build_named_proc_section,
    )

    agent = Agent(
        agent_type=AgentType.NAMED_PROC,
        cl_name="sase",
        project_file="",
        status="RUNNING",
        start_time=datetime(2026, 8, 20, 12, 0, 0),
        raw_suffix="abc123def456",
        agent_name="abc123",
        proc_id="abc123def456",
        proc_status="running",
    )
    row = run_links.context_tool_run_line(
        _brief("ab12cd34" * 4, bucket="pass"), now_ts=_NOW_TS
    )
    with_row = Text()
    for part in build_named_proc_section(agent, tool_run_row=row):
        if isinstance(part, Text):
            with_row.append_text(part)
    assert "Tool run:" in with_row.plain
    without_row = Text()
    for part in build_named_proc_section(agent):
        if isinstance(part, Text):
            without_row.append_text(part)
    assert "Tool run:" not in without_row.plain
