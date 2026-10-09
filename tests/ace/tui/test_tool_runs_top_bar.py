"""Tests for the top-bar tools/bg model and tab-independent refresh."""

from __future__ import annotations

from sase.ace.tui._proc_observer_models import ProcGearLanes
from sase.ace.tui.tool_runs import snapshot as _snapshot_module
from sase.ace.tui.tool_runs.loader import ToolRunGlanceLoaderMixin
from sase.ace.tui.tool_runs.snapshot import (
    ToolRunsLoadState,
    _build_snapshot,
    _set_snapshot,
    apply_loaded_snapshot,
)
from sase.ace.tui.tool_runs.top_bar import (
    bg_tooltip_text,
    tool_run_owner_proc_ids,
    top_bar_tools_model,
)
from sase.ace.tui.widgets.tools_indicator import ToolsIndicator
from sase.core.tool_run import ToolRunGlance

_NOW = 10_000.0


def _glance(
    run_id: str,
    *,
    state: str = "running",
    label: str = "check",
    created_ts: int = 1000,
    last_activity_ts: int = 9_990,
    parent_run_id: str | None = None,
    owner_kind: str | None = None,
    owner_id: str | None = None,
) -> ToolRunGlance:
    return ToolRunGlance(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        last_activity_ts=last_activity_ts,
        stages_done=6,
        stop_requested=False,
        tool_name="check",
        agent=None,
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=parent_run_id,
        running_ts=created_ts,
        current_stage=None,
        stages_expected=11,
        typical_ms=None,
    )


def _lanes(**kwargs: object) -> ProcGearLanes:
    base: dict[str, object] = {
        "bg": 0,
        "tool_procs": 0,
        "monitors": 0,
        "update_rows": (),
        "bg_rows": (),
        "monitor_rows": (),
        "tool_run_ids": frozenset(),
    }
    base.update(kwargs)
    return ProcGearLanes(**base)  # type: ignore[arg-type]


def _clear_snapshot_state() -> None:
    _set_snapshot(None)
    _snapshot_module._TOOL_RUNS_DISABLED_REASON = None
    _snapshot_module._TOOL_RUNS_DISABLED_LOGGED = False


def setup_function(_: object) -> None:
    _clear_snapshot_state()


def teardown_function(_: object) -> None:
    _clear_snapshot_state()


def test_nested_joined_and_parallel_runs_count_once() -> None:
    parent = _glance("parent", created_ts=1000)
    child = _glance("child", created_ts=1100, parent_run_id="parent")
    parallel = _glance("parallel", created_ts=1200)
    dupe = _glance("parent", created_ts=1000)
    snapshot = _build_snapshot((parent, child, parallel, dupe))
    model = top_bar_tools_model(snapshot=snapshot, lanes=_lanes(), now_ts=_NOW)
    assert (model.live, model.silent) == (2, 0)
    assert model.pre_load is False
    assert model.fallback is False


def test_live_child_with_settled_parent_stays_visible() -> None:
    parent = _glance("parent", state="failed", created_ts=1000)
    child = _glance("child", created_ts=1100, parent_run_id="parent")
    snapshot = _build_snapshot((parent, child))
    model = top_bar_tools_model(snapshot=snapshot, lanes=_lanes(), now_ts=_NOW)
    assert (model.live, model.silent) == (1, 0)


def test_silent_and_live_counts_are_disjoint() -> None:
    live = _glance("live", last_activity_ts=9_990)
    silent = _glance("silent", last_activity_ts=9_000)
    snapshot = _build_snapshot((live, silent))
    model = top_bar_tools_model(snapshot=snapshot, lanes=_lanes(), now_ts=_NOW)
    assert (model.live, model.silent) == (1, 1)


def test_pre_load_hides_chips() -> None:
    model = top_bar_tools_model(snapshot=None, lanes=_lanes(), now_ts=_NOW)
    assert model.pre_load is True
    assert (model.live, model.silent) == (0, 0)
    body = ToolsIndicator._build_content(model)
    assert body.plain == ""


def test_stale_renders_dim_chips_with_question_mark() -> None:
    snapshot = _build_snapshot((_glance("a"),))
    fresh = top_bar_tools_model(
        snapshot=snapshot,
        lanes=_lanes(),
        now_ts=_NOW,
        now_mono=100.0,
        failing_since_mono=None,
    )
    assert fresh.stale is False
    assert "?" not in ToolsIndicator._build_content(fresh).plain
    stale = top_bar_tools_model(
        snapshot=snapshot,
        lanes=_lanes(),
        now_ts=_NOW,
        now_mono=100.0,
        failing_since_mono=85.0,
    )
    assert stale.stale is True
    assert (stale.live, stale.silent) == (1, 0)
    assert "?" in ToolsIndicator._build_content(stale).plain
    assert "stale" in stale.tooltip


def test_disabled_fallback_counts_carrier_tags() -> None:
    lanes = _lanes(tool_run_ids=frozenset({"run-a", "run-b"}))
    model = top_bar_tools_model(
        snapshot=None,
        lanes=lanes,
        now_ts=_NOW,
        disabled_reason="missing tool_run binding",
    )
    assert model.fallback is True
    assert model.live == 2
    assert model.tooltip == "ledger unavailable — counting tool procs"


def test_truncated_renders_200_plus() -> None:
    snapshot = _build_snapshot((_glance("a"),), truncated=True)
    model = top_bar_tools_model(snapshot=snapshot, lanes=_lanes(), now_ts=_NOW)
    assert model.truncated is True
    assert "200+" in ToolsIndicator._build_content(model).plain


def test_tools_indicator_orders_chips_and_hides_at_zero() -> None:
    live_only = top_bar_tools_model(
        snapshot=_build_snapshot((_glance("a"),)),
        lanes=_lanes(monitors=1),
        now_ts=_NOW,
    )
    assert ToolsIndicator._build_content(live_only).plain == " ⚒ 1  ⚙ 1 "
    empty = top_bar_tools_model(
        snapshot=_build_snapshot(()),
        lanes=_lanes(),
        now_ts=_NOW,
    )
    assert ToolsIndicator._build_content(empty).plain == ""


def test_tool_run_owner_proc_ids_only_covers_live_proc_owners() -> None:
    live_proc = _glance("a", owner_kind="proc", owner_id="proc-1")
    settled_proc = _glance("b", state="failed", owner_kind="proc", owner_id="proc-2")
    monitor_owned = _glance("c", owner_kind="monitor", owner_id="mon-1")
    snapshot = _build_snapshot((live_proc, settled_proc, monitor_owned))
    assert tool_run_owner_proc_ids(snapshot) == frozenset({"proc-1"})
    assert tool_run_owner_proc_ids(None) == frozenset()


def test_bg_tooltip_names_origin_for_non_ace_rows() -> None:
    from types import SimpleNamespace

    rows = (
        SimpleNamespace(label="sync job", origin="ace"),
        SimpleNamespace(label="manual job", origin="shell"),
    )
    tooltip = bg_tooltip_text(bg_rows=rows)
    assert tooltip.splitlines()[0] == "2 TUI background procs"
    assert "  sync job" in tooltip.splitlines()
    assert "  manual job (shell)" in tooltip.splitlines()
    assert tooltip.splitlines()[-1] == "Click to open the Procs tab"


def test_model_counts_without_lanes_session() -> None:
    # The ledger is session-free: the count survives a TUI restart because
    # it never consults the session, tribe selection, or project filter.
    snapshot = _build_snapshot((_glance("a"), _glance("b")))
    model = top_bar_tools_model(snapshot=snapshot, lanes=None, now_ts=_NOW)
    assert (model.live, model.silent) == (2, 0)


class _OffTabHost(ToolRunGlanceLoaderMixin):
    """Loader host parked on Services with no Agents load yet."""

    current_tab = "services"
    _agents_first_load_done = False
    _agents_loading = False

    def __init__(self) -> None:
        self._tool_runs_load_state = ToolRunsLoadState()
        self.refreshed = 0
        self.indicator_updates = 0

    def _tool_runs_probe_token(self) -> object:
        return ("services-token", 2)

    def _schedule_tool_runs_refresh(self, *, source: str = "unknown") -> None:
        # Record instead of spawning: the gate under test is whether the
        # schedule happens at all off the Agents tab.
        self.refreshed += 1

    def _update_proc_indicator(self) -> None:
        self.indicator_updates += 1


def test_probe_and_schedule_run_off_the_agents_tab() -> None:
    apply_loaded_snapshot(_build_snapshot((_glance("a"),)))
    host = _OffTabHost()
    host._schedule_tool_runs_refresh(source="countdown_tick")
    assert host.refreshed == 1
    host._maybe_probe_tool_runs_drift(source="countdown_tick")
    # Drifted token (no last token) reschedules; the top bar re-evaluates
    # on the same cadence even without a store write.
    assert host.refreshed == 2
    assert host.indicator_updates == 1


def test_agents_entry_reconcile_applies_newer_generation() -> None:
    applied: list[str] = []

    class _AgentsHost(ToolRunGlanceLoaderMixin):
        current_tab = "agents"

        def _apply_tool_runs_snapshot(self, *, source: str = "unknown") -> None:
            applied.append(source)

    apply_loaded_snapshot(_build_snapshot((_glance("a"),), generation=1))
    host = _AgentsHost()
    host._reconcile_tool_runs_on_agents_entry()
    assert applied == ["agents_tab_entry"]
    # A second entry with no newer generation is a no-op.
    host._tool_runs_last_applied_generation = 1
    host._reconcile_tool_runs_on_agents_entry()
    assert applied == ["agents_tab_entry"]
