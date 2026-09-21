"""Focus follows selection on background refresh (plan 202609/agents_panel_focus_follows_selection).

Step 1 inverts ``_sync_panel_group`` so panel focus follows the selected
row instead of snapping the cursor to the focused panel. Steps 2-3 make
navigation during a slow load survive the apply via a fresh apply-seam
capture and a ``prior_pos`` neighbor fallback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.feature_flags import override_flags
from tests.ace.tui.test_agent_panel_index_integration import (
    _Bare as _PanelBare,
)
from tests.ace.tui.test_agent_panel_index_integration import (
    _agent as _panel_agent,
)


def _tribe_agents() -> tuple[Agent, Agent, Agent]:
    a1 = _panel_agent(suffix="a1", tribe="A")
    a2 = _panel_agent(suffix="a2", tribe="A")
    b1 = _panel_agent(suffix="b1", tribe="B")
    return a1, a2, b1


def test_focus_follows_selection_when_tribe_changes_under_selection() -> None:
    """M1b: the selected agent's tribe changes while its panel still has rows."""
    a1, a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, a2, b1])
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("A")
    bare.current_idx = 0
    selected_identity = a1.identity

    moved = _panel_agent(suffix="a1", tribe="B")
    assert moved.identity == selected_identity
    bare._agents = [moved, a2, b1]

    bare._sync_panel_group()

    assert bare._agents[bare.current_idx].identity == selected_identity
    assert bare._panel_group.focused_key == "B"
    assert getattr(bare, "_expanded_panel_focus", False) is False


def test_cursor_stays_when_focused_panel_vanishes() -> None:
    """M1a: vanishing focused panel must not yank the cursor to panel 0."""
    a1 = _panel_agent(suffix="a1", tribe="A")
    b1 = _panel_agent(suffix="b1", tribe="B")
    c1 = _panel_agent(suffix="c1", tribe="C")
    bare = _PanelBare([a1, b1, c1])
    assert bare._panel_group.panel_keys == ["A", "B", "C"]
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("C")
    bare.current_idx = 1
    assert b1.identity == bare._agents[bare.current_idx].identity

    bare._agents = [a1, b1]

    bare._sync_panel_group()

    assert bare._agents[bare.current_idx].identity == b1.identity
    assert bare._panel_group.focused_key == "B"
    assert bare.current_idx != 0 or bare._agents[0].identity == b1.identity


def test_parked_whole_panel_focus_preserves_snap() -> None:
    """Parked (a): whole-panel focus keeps today's snap behavior."""
    a1, _a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, b1])
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("A")
    bare.current_idx = 1
    bare._expanded_panel_focus = True  # type: ignore[attr-defined]

    bare._sync_panel_group()

    assert bare._panel_group.focused_key == "A"
    assert bare.current_idx == 0
    assert bare._agents[bare.current_idx].identity == a1.identity


def test_parked_empty_strip_preserves_snap(monkeypatch: Any) -> None:
    """Parked (b): a focused strip that renders no rows keeps the snap."""
    a1, _a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, b1])
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("A")
    bare.current_idx = 1
    bare._expanded_panel_focus = False  # type: ignore[attr-defined]
    bare._current_group_key = None  # type: ignore[attr-defined]

    from sase.ace.tui.actions.agents import (
        _display_panel_collection as collection_mod,
    )

    def _empty_slice(_owner: Any, _key: Any) -> tuple[list[int], list[Agent]]:
        return [], []

    monkeypatch.setattr(collection_mod, "rendered_panel_slice", _empty_slice)

    bare._sync_panel_group()

    assert bare._panel_group.focused_key == "A"
    assert bare.current_idx == 0


def test_parked_banner_focus_preserves_snap() -> None:
    """Parked (c): banner focus keeps today's snap behavior."""
    a1, _a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, b1])
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("A")
    bare.current_idx = 1
    bare._expanded_panel_focus = False  # type: ignore[attr-defined]
    bare._current_group_key = ("A",)  # type: ignore[attr-defined]

    bare._sync_panel_group()

    assert bare._panel_group.focused_key == "A"
    assert bare.current_idx == 0


def test_parked_collapsed_focus_preserves_snap() -> None:
    """Parked (d): whole-panel focus on a collapsed strip is preserved."""
    a1, _a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, b1])
    bare._collapsed_panel_keys = {"B"}  # type: ignore[attr-defined]
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("B")
    bare.current_idx = 0
    bare._expanded_panel_focus = False  # type: ignore[attr-defined]
    bare._current_group_key = None  # type: ignore[attr-defined]

    bare._sync_panel_group()

    assert bare._panel_group.focused_key == "B"
    assert bare._agents[bare.current_idx].identity == b1.identity


def test_parked_cursor_in_collapsed_panel_snaps_out() -> None:
    """Parked (e): a cursor stranded in a collapsed panel is evacuated."""
    a1, _a2, b1 = _tribe_agents()
    bare = _PanelBare([a1, b1])
    bare._collapsed_panel_keys = {"A"}  # type: ignore[attr-defined]
    bare._panel_group.focused_idx = bare._panel_group.panel_keys.index("B")
    bare.current_idx = 0
    bare._expanded_panel_focus = False  # type: ignore[attr-defined]
    bare._current_group_key = None  # type: ignore[attr-defined]

    bare._sync_panel_group()

    assert bare._panel_group.focused_key == "B"
    assert bare._agents[bare.current_idx].identity == b1.identity


class _FakeContentCache:
    def get_haystack(self, _agent: Agent) -> str:
        return ""

    def prune(self, _agents: Any) -> None:
        pass


class _ApplyCaptureApp(AgentLoadingMixin):
    """Minimal async-load harness that captures the apply-seam selection."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self.hide_non_run_agents = False
        self._agent_search_query = ""
        self._agent_query_cache = None
        self._agent_query_parse_error = None
        self._agent_content_search_cache = _FakeContentCache()  # type: ignore[assignment]
        self._agent_content_search_index = None
        self._agent_content_search_source_generation = 0
        self._agent_content_search_refresh_generation = 0
        self._agent_status_overrides: dict[Any, Any] = {}
        self._dismissed_agents: set[Any] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._unread_completed_agent_ids: set[Any] = set()
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = False
        self._agents_capacity_generation = 0
        self._agents_capacity_with_children: list[Agent] = list(agents)
        self._agents_refresh_active_source = "unknown"
        self._agents_first_load_done = True
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._agents_applied_query_key = None
        self._agents_complete_history_query_key = None
        self.applied: tuple[bool, Any] | None = None

    def _should_seed_agent_search_query(self) -> bool:
        return False

    def _external_dismissal_merge_result(self, _snapshot: Any) -> None:
        return None

    def _apply_external_dismissal_merge(self, _result: Any) -> None:
        return None

    async def _prepare_agent_content_search_index_async(
        self, _agents: list[Agent]
    ) -> None:
        # Simulate j/k navigation during the slow load: move to the last row.
        self.current_idx = len(self._agents) - 1
        return None

    def _fleet_rows_for_prepared_snapshot(self) -> tuple[Agent, ...]:
        return ()

    def _apply_loaded_agents_prepared(self, *args: Any, **kwargs: Any) -> None:
        self.applied = (kwargs["on_agents_tab"], kwargs["selected_identity"])

    def _schedule_loader_cleanup(self, *args: Any, **kwargs: Any) -> None:
        return None

    def _schedule_monitor_reconcile(self, *args: Any, **kwargs: Any) -> None:
        return None

    def _record_slow_loader_stages(self, *args: Any, **kwargs: Any) -> None:
        return None


def _tier1_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


async def test_full_load_apply_seam_recaptures_moved_selection() -> None:
    """Step 2 (full): navigation during worker awaits reaches the apply."""
    first = _panel_agent(suffix="first", tribe="A")
    second = _panel_agent(suffix="second", tribe="A")
    app = _ApplyCaptureApp([first, second])
    app.current_idx = 0
    load_state = _tier1_state()

    from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult

    def _fake_disk(_snapshot: Any, **_kwargs: Any) -> tuple[Any, None]:
        return (
            _AgentDiskLoadResult(
                all_agents=[first, second],
                dismissed_from_loader=[],
                load_state=load_state,
            ),
            None,
        )

    with (
        patch(
            "sase.ace.patch.find_all_patches_cached",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.agents._loading_disk_full.disk_load_with_optional_current_project",
            side_effect=_fake_disk,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        ok = await app._load_agents_async(source="test")

    assert ok is True
    assert app.applied is not None
    on_tab, selected_identity = app.applied
    assert on_tab is True
    assert selected_identity == second.identity


async def test_delta_load_apply_seam_recaptures_moved_selection() -> None:
    """Step 2 (delta): navigation during worker awaits reaches the apply."""
    first = _panel_agent(suffix="first", tribe="A")
    second = _panel_agent(suffix="second", tribe="A")
    app = _ApplyCaptureApp([first, second])
    app.current_idx = 0
    load_state = _tier1_state()

    from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult

    def _fake_delta(_snapshot: Any, _dirs: Any, **_kwargs: Any) -> _AgentDiskLoadResult:
        return _AgentDiskLoadResult(
            all_agents=[first, second],
            dismissed_from_loader=[],
            load_state=load_state,
        )

    with (
        patch(
            "sase.ace.patch.find_all_patches_cached",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.agents._loading_helpers.load_agent_artifact_delta_from_disk_with_state",
            side_effect=_fake_delta,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        from pathlib import Path

        ok = await app._load_agent_artifact_delta_async([Path("/tmp/x")])

    assert ok is True
    assert app.applied is not None
    on_tab, selected_identity = app.applied
    assert on_tab is True
    assert selected_identity == second.identity


def test_capture_helper_returns_off_tab_identity() -> None:
    """The shared helper preserves the off-tab fallback."""
    first = _panel_agent(suffix="first", tribe="A")
    app = _ApplyCaptureApp([first])
    app.current_tab = "patches"  # type: ignore[assignment]
    app._agents_last_identity = first.identity
    on_tab, selected_identity = app._capture_agents_apply_selection()
    assert on_tab is False
    assert selected_identity == first.identity


class _RefreshFallbackApp(AgentsMixinCore):
    """Harness with the real finalize + visible-order focus restoration."""

    def __init__(self, agents: list[Agent], *, current_idx: int = 0) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._agents_local_with_children: list[Agent] = list(agents)
        self._agents_local_visible: list[Agent] = list(agents)
        self._agents_capacity_with_children: list[Agent] = list(agents)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self.hide_non_run_agents = False
        self._agent_search_query = ""
        self._agent_query_cache = None
        self._agent_query_parse_error = None
        self._agent_content_search_cache = _FakeContentCache()  # type: ignore[assignment]
        self._agent_content_search_index = None
        self._agent_content_search_source_generation = 0
        self._agent_content_search_refresh_generation = 0
        self._agent_status_overrides = {}
        self._dismissed_agents = set()
        self._dismissed_agent_objects = []
        self._unread_completed_agent_ids = set()
        self._manual_unread_agent_ids = set()
        self._agent_display_status_by_identity = {}
        self._fold_manager = FoldStateManager()
        self._fold_counts = {}
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key = None
        self._expanded_panel_focus = False
        self._panel_selection_memory = {}
        self._panel_group = AgentPanelGroup.from_agents(list(agents))
        self._agent_panels_grouped = False
        self._collapsed_panel_keys = set()
        self._expanded_panel_keys = set()
        self._nav_stops_cache = None
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self._agent_neighbor_index_cache = None
        self._unread_jump_candidates_cache = None
        self._agents_first_load_done = True
        self._agents_seen_complete_history = False
        self._agents_complete_history_query_key = None
        self._agents_applied_query_key = None
        self._agent_load_state = None
        self._agents_refresh_active_source = "unknown"
        self._agents_refresh_scheduled = False
        self._live_hints_scan_scheduled = False
        self._live_hints_scan_running = False
        self._live_hints_scan_pending = False
        self._live_hints_scan_source = "unknown"
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._diff_badge_scan_scheduled = False
        self._diff_badge_scan_running = False
        self._diff_badge_scan_pending = False
        self._diff_badge_scan_source = "unknown"

    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        return None

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("widgets not mounted")


def _visible_order_agent(
    *, project: str, cl: str, name: str, status: str = "RUNNING"
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        pid=12345,
        raw_suffix=f"{name}-suffix",
    )


def test_refresh_prior_pos_lands_on_visually_below_row() -> None:
    """Step 3: a removed middle row falls back to the visible neighbor."""
    zeta = _visible_order_agent(project="zeta", cl="z1", name="z1")
    alpha = _visible_order_agent(project="alpha", cl="a1", name="a1")
    beta = _visible_order_agent(project="beta", cl="b1", name="b1")
    agents = [zeta, alpha, beta]
    # Visible order is [alpha, beta, zeta]; select beta (middle).
    app = _RefreshFallbackApp(agents, current_idx=2)
    prior_pos = app._capture_focused_visible_pos()
    assert prior_pos == 1

    removed_identity = beta.identity
    app._agents = [zeta, alpha]
    app._agents_with_children = [zeta, alpha]
    app._invalidate_agent_panel_cache()

    with override_flags(agents_unified_query=False):
        app._finalize_agent_list(
            True,
            removed_identity,
            save_unfiltered=False,
            fold_filter_already_applied=True,
            prior_pos=prior_pos,
            previous_agents=agents,
            refresh_display=False,
        )

    # Visually below beta was zeta; the global-index clamp would land on alpha.
    assert app._agents[app.current_idx].agent_name == "z1"


def test_apply_inner_passes_prior_pos_to_finalize(monkeypatch: Any) -> None:
    """Step 3 wiring: the prepared apply forwards the pre-mutation anchor."""
    from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData

    zeta = _visible_order_agent(project="zeta", cl="z1", name="z1")
    alpha = _visible_order_agent(project="alpha", cl="a1", name="a1")
    beta = _visible_order_agent(project="beta", cl="b1", name="b1")
    agents = [zeta, alpha, beta]
    app = _RefreshFallbackApp(agents, current_idx=2)

    captured: dict[str, Any] = {}

    def _fake_finalize(
        on_tab: bool,
        selected_identity: Any,
        *,
        save_unfiltered: bool,
        fold_filter_already_applied: bool = False,
        prior_pos: int | None = None,
        precomputed_plan: Any = None,
        previous_agents: Any = None,
        refresh_display: bool = True,
    ) -> None:
        captured["prior_pos"] = prior_pos
        captured["on_tab"] = on_tab

    monkeypatch.setattr(app, "_finalize_agent_list", _fake_finalize)
    monkeypatch.setattr(
        app,
        "_schedule_agents_post_roster_startup_work",
        lambda **_: None,
        raising=False,
    )
    monkeypatch.setattr(
        app, "_schedule_live_hint_refresh", lambda **_: None, raising=False
    )
    monkeypatch.setattr(
        app, "_schedule_bead_confirmation_warmup", lambda **_: None, raising=False
    )
    monkeypatch.setattr(
        app, "_schedule_diff_badge_classification", lambda **_: None, raising=False
    )
    monkeypatch.setattr(
        app, "_schedule_agents_fleet_refresh", lambda **_: None, raising=False
    )

    prep = PreparedApplyData(
        filtered_agents=list(agents),
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=True,
        selected_identity=beta.identity,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
    )

    assert captured["on_tab"] is True
    assert captured["prior_pos"] == 1
