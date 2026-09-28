"""Tests for the header-chip phase (epic sase-1bt, sase-1bt.5)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from sase.ace.tui.tool_runs.header_chip import (
    header_chip_for_node,
    header_run_id_for_agent,
    tool_runs_field_entries,
)
from sase.ace.tui.tool_runs.summaries import (
    node_live_runs,
    resolve_tool_run_summary,
    selector_for_agent,
)
from sase.core.tool_run import (
    ToolRunBrief,
    ToolRunGlance,
    ToolRunNodeSummary,
    ToolRunVerdictSummary,
)
from sase.feature_flags import override_flags

_NOW = 2000.0


def _verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        unknown=int(counts.get("unknown", 0)),
        reasons=tuple(counts.get("reasons", ())),
    )


def _brief(
    run_id: str,
    label: str = "check",
    bucket: str = "pass",
    *,
    state: str = "succeeded",
    created_ts: int = 1000,
    settled_ts: int | None = 1500,
    duration_ms: int | None = 241000,
    agent: str | None = "0t9--code",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    terminal_cause: str | None = None,
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        verdict=_verdict(bucket, **counts),
        settled_ts=settled_ts,
        duration_ms=duration_ms,
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        terminal_cause=terminal_cause,
    )


def _glance(
    run_id: str,
    *,
    agent: str | None = "0t9--code",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    state: str = "running",
    label: str = "check",
    created_ts: int = 1000,
    last_activity_ts: int = 1990,
    stages_done: int = 6,
    stages_expected: int | None = 11,
    parent_run_id: str | None = None,
    stop_requested: bool = False,
    typical_ms: int | None = None,
) -> ToolRunGlance:
    return ToolRunGlance(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        last_activity_ts=last_activity_ts,
        stages_done=stages_done,
        stop_requested=stop_requested,
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=parent_run_id,
        running_ts=created_ts,
        current_stage=None,
        stages_expected=stages_expected,
        typical_ms=typical_ms,
    )


def _node(agent_name: str = "0t9--code", **over: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "agent_name": agent_name,
        "monitor_id": None,
        "proc_id": None,
        "is_monitor": False,
        "is_named_proc": False,
        "is_agent_session_container_row": False,
        "followup_agents": [],
        "runtime_children": [],
        "agent_session_reference_name": None,
        "fleet_origin_alias": None,
        "is_clan_container": False,
        "start_time": None,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


def _summary(
    briefs: tuple[ToolRunBrief, ...] = (),
    live: tuple[ToolRunGlance, ...] = (),
) -> ToolRunNodeSummary:
    return ToolRunNodeSummary(
        key="agent:0t9--code",
        total_runs=len(briefs),
        live=live,
        latest_by_tool=briefs,
        runs=briefs,
    )


def test_chip_per_bucket() -> None:
    cases = [
        ("pass", "✓"),
        ("new_failures", "✗ 3 NEW"),
        ("known_only", "≈ known only"),
        ("undetermined", "? 2 UNKNOWN"),
        ("killed", "⊘ killed"),
        ("stopped", "⊘ stopped"),
        ("lost", "⊘ lost"),
    ]
    for bucket, fragment in cases:
        counts: dict[str, Any] = {"new": 3, "known": 1, "unknown": 2}
        terminal = "signal" if bucket == "killed" else None
        with override_flags(ace_tool_runs=True):
            rendered = header_chip_for_node(
                _node(),
                _summary(
                    (_brief("r1", bucket=bucket, terminal_cause=terminal, **counts),)
                ),
                now_ts=_NOW,
            )
        assert rendered is not None, bucket
        text, _style, run_id = rendered
        assert fragment in text, (bucket, text)
        assert text.startswith("⚒ check "), (bucket, text)
        assert ":" in text, (bucket, text)  # settled times are absolute
        assert run_id == "r1"


def test_untriaged_chip() -> None:
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(),
            _summary((_brief("r1", bucket="undetermined", reasons=("not_triaged",)),)),
            now_ts=_NOW,
        )
    assert rendered is not None
    assert "? untriaged" in rendered[0]


def test_live_chip_progress_typical_and_amber() -> None:
    run = _glance("live1", stages_done=6, stages_expected=11, typical_ms=253000)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[run], now_ts=133.0 + 1000
        )
    assert rendered is not None
    text, style, run_id = rendered
    assert "7/11" in text, text
    assert "typ 4m13s" in text, text
    assert style == "bold #87D7FF", style
    assert run_id == "live1"

    old = _glance("live2", stages_done=1, stages_expected=None, typical_ms=240000)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[old], now_ts=1600.0
        )
    assert rendered is not None
    assert rendered[1] == "bold #FFAF5F", rendered  # elapsed past typical turns amber


def test_silent_chip_and_starting_stopping() -> None:
    silent = _glance("s1", last_activity_ts=500)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[silent], now_ts=_NOW
        )
    assert rendered is not None
    assert rendered[0].startswith("⚒⚠"), rendered[0]
    assert "silent" in rendered[0]
    assert rendered[1] == "bold #FF5F5F"

    starting = _glance("s2", state="created")
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[starting], now_ts=_NOW
        )
    assert rendered is not None and "starting" in rendered[0]

    stopping = _glance("s3", stop_requested=True)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[stopping], now_ts=_NOW
        )
    assert rendered is not None and "stopping" in rendered[0]


def test_multi_label_severity_and_plus_n() -> None:
    briefs = (
        _brief("p1", label="test", bucket="pass"),
        _brief("n1", label="check", bucket="new_failures", new=3, known=1),
    )
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(_node(), _summary(briefs), now_ts=_NOW)
    assert rendered is not None
    assert "✗ 3 NEW" in rendered[0], rendered[0]
    assert rendered[0].endswith("+1"), rendered[0]
    assert rendered[2] == "n1"


def test_live_outranks_settled_and_silent_outranks_live() -> None:
    settled = _summary((_brief("old", bucket="new_failures", new=5),))
    live = _glance("live1", created_ts=1500, last_activity_ts=1990)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), settled, snapshot_runs=[live], now_ts=_NOW
        )
    assert rendered is not None and rendered[2] == "live1"

    quiet = _glance("live2", created_ts=1400, last_activity_ts=1995)
    loud = _glance("live3", created_ts=1500, last_activity_ts=500)
    with override_flags(ace_tool_runs=True):
        rendered = header_chip_for_node(
            _node(), None, snapshot_runs=[quiet, loud], now_ts=_NOW
        )
    assert rendered is not None and rendered[2] == "live3"


def test_session_selector_unions_members_and_container_name() -> None:
    agent = _node(
        "sess",
        is_agent_session_container_row=True,
        followup_agents=[SimpleNamespace(agent_name="m1")],
        runtime_children=[SimpleNamespace(agent_name="m2")],
        agent_session_reference_name=lambda: "sess",
    )
    selector = selector_for_agent(agent)
    assert selector is not None
    assert set(selector.agents) == {"m1", "m2", "sess"}

    stranger = _glance("z", agent="other")
    member = _glance("a", agent="m1")
    own = _glance("b", agent="sess")
    dup = _glance("a", agent="m1")
    child = _glance("c", agent="m1", parent_run_id="a")
    matched = node_live_runs([stranger, member, own, dup, child], selector)
    assert [run.run_id for run in matched] == ["a", "b"]


def test_since_ts_guards_reused_names() -> None:
    agent = _node("x")
    selector = selector_for_agent(agent)
    assert selector is not None
    import dataclasses

    selector = dataclasses.replace(selector, since_ts=1500)
    old = _glance("old", agent="x", created_ts=1000)
    new = _glance("new", agent="x", created_ts=1600)
    assert node_live_runs([old, new], selector) == (new,)


def test_monitor_selector_and_starter_annotation() -> None:
    agent = _node("starter", is_monitor=True, monitor_id="m1")
    selector = selector_for_agent(agent)
    assert selector is not None
    assert selector.owners == (("monitor", "m1"),)

    owned = _brief(
        "mrun1",
        bucket="pass",
        agent="starter",
        owner_kind="monitor",
        owner_id="m1",
    )
    overlay = _glance("mrun1", agent="starter", owner_kind="monitor", owner_id="m1")
    with override_flags(ace_tool_runs=True):
        entries = tool_runs_field_entries(
            agent, _summary((owned,)), snapshot_runs=[overlay], now_ts=_NOW
        )
    assert len(entries) == 1
    assert entries[0].text.endswith(" · starter"), entries[0].text

    turn = _node("starter")
    handed = _brief(
        "hrun1", bucket="pass", agent="starter", owner_kind="monitor", owner_id="m1"
    )
    with override_flags(ace_tool_runs=True):
        entries = tool_runs_field_entries(turn, _summary((handed,)), now_ts=_NOW)
    assert entries[0].text.endswith(" → monitor m1"), entries[0].text


def test_remote_and_clan_have_no_chip_or_field() -> None:
    remote = _node("x", fleet_origin_alias="far")
    clan = _node("x", is_clan_container=True)
    run = _glance("a", agent="x")
    brief = _summary((_brief("b1", bucket="pass"),))
    with override_flags(ace_tool_runs=True):
        assert (
            header_chip_for_node(remote, brief, snapshot_runs=[run], now_ts=_NOW)
            is None
        )
        assert (
            header_chip_for_node(clan, brief, snapshot_runs=[run], now_ts=_NOW) is None
        )
        assert (
            tool_runs_field_entries(remote, brief, snapshot_runs=[run], now_ts=_NOW)
            == ()
        )
        assert (
            tool_runs_field_entries(clan, brief, snapshot_runs=[run], now_ts=_NOW) == ()
        )
    assert selector_for_agent(remote) is None
    assert selector_for_agent(clan) is None


def test_flag_off_has_no_surfaces() -> None:
    run = _glance("a", agent="x")
    brief = _summary((_brief("b1", bucket="pass"),))
    with override_flags(ace_tool_runs=False):
        assert (
            header_chip_for_node(_node(), brief, snapshot_runs=[run], now_ts=_NOW)
            is None
        )
        assert (
            tool_runs_field_entries(_node(), brief, snapshot_runs=[run], now_ts=_NOW)
            == ()
        )
        assert resolve_tool_run_summary(_node(), store_token="t") is None
        assert header_run_id_for_agent(object(), _node()) is None


def test_field_entries_format_per_label() -> None:
    briefs = (
        _brief(
            "6c3d5107" + "0" * 24, label="check", bucket="new_failures", new=3, known=1
        ),
        _brief("81ef0cb1" + "0" * 24, label="test", bucket="pass"),
    )
    with override_flags(ace_tool_runs=True):
        entries = tool_runs_field_entries(_node(), _summary(briefs), now_ts=_NOW)
    assert [entry.text for entry in entries] == [
        "check ✗ 3 NEW · 1 KNOWN 6c3d5107",
        "test ✓ 81ef0cb1",
    ]
    assert entries[0].run_id == "6c3d5107" + "0" * 24


def test_lru_hit_avoids_reload_and_stale_load_rejected(monkeypatch) -> None:
    import sase.core.tool_run as core_tool_run

    calls = []

    def _fake(request: Any, **kwargs: Any) -> Any:
        calls.append(request)
        return SimpleNamespace(
            nodes=(
                SimpleNamespace(
                    key="agent:x",
                    total_runs=1,
                    truncated=False,
                    live=(),
                    latest_by_tool=(),
                    runs=(),
                ),
            )
        )

    monkeypatch.setattr(core_tool_run, "tool_run_node_summaries", _fake)
    with override_flags(ace_tool_runs=True):
        first = resolve_tool_run_summary(_node("x"), store_token="t1")
        assert first is not None
        assert len(calls) == 1
        assert calls[0]["nodes"][0]["agents"] == ["x"]
        second = resolve_tool_run_summary(_node("x"), store_token="t1")
        assert second is first
        assert len(calls) == 1
        stale = resolve_tool_run_summary(
            _node("x"), store_token="t2", is_current=lambda: False
        )
        assert stale is None  # j/k moved on mid-load: never published
        assert len(calls) == 2
        # The stale load still cached under its token for the next selection.
        assert resolve_tool_run_summary(_node("x"), store_token="t2") is not None
        assert len(calls) == 2


def test_copy_registry_keymap_and_dispatch_cover_tool_run_id() -> None:
    from sase.ace.tui._copy_target_registry import COPY_TARGETS
    from sase.ace.tui.actions.clipboard._palette_registry import _DISPATCH_ORDER
    from sase.ace.tui.copy_targets import copy_targets_for
    from sase.ace.tui.keymaps.mode_keymaps import CopyModeKeymaps

    defaults = CopyModeKeymaps().keys
    assert isinstance(defaults, dict)
    agents_keys = defaults["agents"]
    assert isinstance(agents_keys, dict)
    assert agents_keys["tool_run_id"] == "r"

    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["copy_mode"]["keys"]["agents"]
    assert configured["tool_run_id"] == "r"

    targets = {target.target for target in copy_targets_for("agents")}
    assert "tool_run_id" in targets
    assert "tool_run_id" in _DISPATCH_ORDER["agents"]
    assert {target.group for target in COPY_TARGETS} == set(defaults)


def test_header_run_id_for_agent_copies_full_id(monkeypatch) -> None:
    import sase.ace.tui.tool_runs.header_chip as header_chip_module

    full_id = "6c3d5107" + "f" * 24
    summary = _summary((_brief(full_id, bucket="new_failures", new=1),))
    panels = {"prompt": SimpleNamespace()}

    class _Detail:
        def query_one(self, selector: str) -> object:
            assert selector == "#agent-prompt-panel"
            return panels["prompt"]

    class _App:
        def query_one(self, selector: str) -> object:
            assert selector == "#agent-detail-panel"
            return _Detail()

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "get_cached_detail_header_summary",
        lambda _widget, _agent: SimpleNamespace(tool_run_summary=summary),
    )
    with override_flags(ace_tool_runs=True):
        assert header_run_id_for_agent(_App(), _node()) == full_id
    with override_flags(ace_tool_runs=False):
        assert header_run_id_for_agent(_App(), _node()) is None
    assert header_chip_module.header_run_id_for_agent(None, _node()) is None


def test_compact_header_renders_chip_through_real_builder() -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        DetailHeaderSummary,
    )
    from sase.ace.tui.widgets.prompt_panel._identity_header_compact import (
        build_agent_compact_lines,
    )
    from tests.ace.tui.widgets._agent_display_helpers import make_agent

    agent = make_agent(agent_name="0t9--code")
    summary = DetailHeaderSummary(
        tool_run_summary=_summary(
            (_brief("n1", bucket="new_failures", new=3, known=1),)
        )
    )
    with override_flags(ace_tool_runs=True):
        compact = build_agent_compact_lines(agent=agent, summary=summary)
    assert isinstance(compact, Text)
    assert "⚒ check" in compact.plain, compact.plain
    assert "3 NEW" in compact.plain, compact.plain
    with override_flags(ace_tool_runs=False):
        compact = build_agent_compact_lines(agent=agent, summary=summary)
    assert "⚒" not in compact.plain, compact.plain


def test_expanded_metadata_renders_tool_runs_field() -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata import (
        append_agent_metadata_fields,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        DetailHeaderSummary,
    )
    from tests.ace.tui.widgets._agent_display_helpers import make_agent

    agent = make_agent(agent_name="0t9--code")
    summary = DetailHeaderSummary(
        tool_run_summary=_summary(
            (
                _brief("6c3d5107" + "0" * 24, label="check", bucket="pass"),
                _brief("81ef0cb1" + "0" * 24, label="test", bucket="pass"),
            )
        )
    )
    with override_flags(ace_tool_runs=True):
        text = Text()
        append_agent_metadata_fields(
            text,
            agent,
            cheap=True,
            hint_state=None,
            summary=summary,
            agent_status_buckets=None,
            cached_bead_display=lambda _agent: None,
        )
    assert "Tool runs: " in text.plain, text.plain
    assert "check ✓ 6c3d5107" in text.plain, text.plain
    with override_flags(ace_tool_runs=False):
        text = Text()
        append_agent_metadata_fields(
            text,
            agent,
            cheap=True,
            hint_state=None,
            summary=summary,
            agent_status_buckets=None,
            cached_bead_display=lambda _agent: None,
        )
    assert "Tool runs:" not in text.plain, text.plain


def test_tool_runs_lane_resolves_through_header_summary(monkeypatch) -> None:
    from tests.ace.tui.widgets._agent_display_helpers import make_agent

    import sase.ace.tui.tool_runs.summaries as summaries_module

    agent = make_agent(agent_name="lane-agent")
    summary = _summary((_brief("lane1", bucket="pass"),))
    monkeypatch.setattr(
        summaries_module, "resolve_tool_run_summary", lambda _agent, **_kw: summary
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    with override_flags(ace_tool_runs=True):
        built = build_detail_header_summary(agent, lanes=frozenset({"tool-runs"}))
    assert built.ready_lanes == frozenset({"tool-runs"})
    assert built.tool_run_summary is summary
