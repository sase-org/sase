"""Axe-tab navigation must not hit disk.

Before this change, Ctrl+N / Ctrl+P on the Axe tab re-read every
lumberjack's status, metrics, and log tail from disk on each keypress.
With many lumberjacks configured this stalled the TUI for hundreds of
milliseconds to seconds per press.

The fix routes navigation through the cache populated by the async
collector — no on-disk reads happen on the navigation path. This test
pins that invariant by monkeypatching the disk readers to raise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display import (
    AxeDisplayMixin,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
)
from sase.axe.state import LumberjackMetrics, LumberjackStatus


def _status(name: str) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=1,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=60,
    )


class FakeAxeApp(AxeDisplayMixin):
    """Minimal stand-in exposing the axe-display surface for unit tests."""

    def __init__(self) -> None:
        self.current_tab = "axe"
        self.current_idx = 0
        self.refresh_interval = 10
        self.axe_running = True
        self._countdown_remaining = 10
        self._axe_status = None
        self._axe_metrics = None
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view = "axe"
        self._bgcmd_slots = []
        self._axe_lumberjack_names = ["hooks", "checks"]
        self._axe_lumberjack_idx = 0
        self._axe_items = [
            LumberjackItem(name="hooks"),
            ChopItem(lumberjack_name="hooks", chop_name="fast"),
            LumberjackItem(name="checks"),
            BgCmdItem(slot=1),
        ]
        self._bang_mode_active = False
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._axe_first_load_done = True
        # Cache populated with fake entries so navigation can render.
        self._axe_lumberjack_statuses: dict[str, LumberjackStatus | None] = {
            "hooks": _status("hooks"),
            "checks": _status("checks"),
        }
        self._axe_lumberjack_metrics: dict[str, LumberjackMetrics | None] = {
            "hooks": LumberjackMetrics(chops_executed=3),
            "checks": LumberjackMetrics(chops_executed=1),
        }
        self._axe_lumberjack_log_tails = {
            "hooks": "hooks log\n",
            "checks": "checks log\n",
        }
        self._axe_bgcmd_details = {
            1: BgCmdSnapshot(info=None, running=True, output_tail="slot log\n"),
        }
        self._axe_lumberjack_chop_names = {"hooks": ["fast"], "checks": []}
        self._axe_chop_snapshots: dict[tuple[str, str], ChopSnapshot] = {
            ("hooks", "fast"): ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="fast",
                description="fast desc",
                runs=[],
            ),
        }
        self._axe_lumberjack_snapshots: dict[str, LumberjackSnapshot] = {
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=_status("hooks"),
                metrics=LumberjackMetrics(chops_executed=3),
                log_tail="hooks log\n",
                chops=[self._axe_chop_snapshots[("hooks", "fast")]],
            ),
            "checks": LumberjackSnapshot(
                name="checks",
                status=_status("checks"),
                metrics=LumberjackMetrics(chops_executed=1),
                log_tail="checks log\n",
                chops=[],
            ),
        }
        self._axe_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]

    # Stubs for attributes / methods AxeDisplayMixin reaches for.
    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return MagicMock()

    def set_timer(self, delay: float, callback: Any) -> Any:
        timer = MagicMock()
        timer.stop = MagicMock()
        # Remember scheduled callbacks so tests can drive the debounce.
        self._scheduled_callbacks.append((delay, callback))
        return timer

    _scheduled_callbacks: list[tuple[float, Any]] = []

    # No-op helpers called by refresh_axe_display.
    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)


class _DescriptionDashboardProbe:
    """Track the fixed-banner text selected by the AXE render path."""

    def __init__(self) -> None:
        self.banner: str | None = None

    def update_lumberjack_overview(
        self, *, snapshot: LumberjackSnapshot, **_kwargs: Any
    ) -> None:
        self.banner = snapshot.description or "No description configured"

    def update_chop_run_display(
        self, *, snapshot: ChopSnapshot, **_kwargs: Any
    ) -> None:
        self.banner = snapshot.description or "No description configured"
        if snapshot.generated and snapshot.target_key:
            self.banner += f"  · {snapshot.target_key}"

    def update_bgcmd_display(self, *_args: Any, **_kwargs: Any) -> None:
        self.banner = None


class _ToggleProbe:
    """Minimal action host proving the toggle stays cache-only."""

    def __init__(self, tab: str = "axe") -> None:
        self.current_tab = tab
        self.axe_description_expanded = True
        self.dashboard = MagicMock()
        self.refreshes = 0

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.dashboard

    def _refresh_axe_display(self) -> None:
        self.refreshes += 1


def test_description_toggle_persists_and_repaints_both_directions() -> None:
    app = _ToggleProbe()

    AxeMixin.action_toggle_axe_description(app)  # type: ignore[arg-type]
    assert app.axe_description_expanded is False
    app.dashboard.refresh_description_banner.assert_called_once_with(False)
    assert app.refreshes == 1

    # Selection changes do not reset the session state; the next toggle simply
    # reverses the same cached boolean.
    AxeMixin.action_toggle_axe_description(app)  # type: ignore[arg-type]
    assert app.axe_description_expanded is True
    app.dashboard.refresh_description_banner.assert_called_with(True)
    assert app.refreshes == 2


def test_description_toggle_is_noop_outside_axe_tab() -> None:
    app = _ToggleProbe(tab="agents")

    AxeMixin.action_toggle_axe_description(app)  # type: ignore[arg-type]

    assert app.axe_description_expanded is True
    app.dashboard.refresh_description_banner.assert_not_called()
    assert app.refreshes == 0


def test_description_config_seeds_session_default() -> None:
    from sase.ace.tui.app import AceApp

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"axe_description_expanded": False}},
    ):
        app = AceApp(auto_start_axe=False)

    assert app.axe_description_expanded is False


def test_d_resolves_to_description_on_axe_and_diff_on_prs() -> None:
    from sase.ace.tui.app import AceApp

    def resolved(app: AceApp) -> str | None:
        for binding in app._bindings.get_bindings_for_key("d"):
            if app.check_action(binding.action, ()) is not False:
                return binding.action
        return None

    axe_app = AceApp(auto_start_axe=False, initial_tab="axe")
    assert resolved(axe_app) == "toggle_axe_description"

    prs_app = AceApp(auto_start_axe=False, initial_tab="patches")
    prs_app._reactive_current_artifacts_subtab = "prs"
    assert resolved(prs_app) == "show_diff"

    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    assert resolved(agents_app) != "show_diff"


def test_navigation_does_not_read_from_disk() -> None:
    """A navigation-driven display refresh never touches disk readers.

    Monkeypatches every per-lumberjack and per-slot reader to raise. If
    navigation still funnels through them, these tests fail loudly rather
    than silently regressing the "instant j/k" property.
    """
    app = FakeAxeApp()
    app._scheduled_callbacks = []

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("navigation must not read from disk")

    with (
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_status",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_metrics",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_log_tail",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_slot_output_tail",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._render.get_slot_info",
            side_effect=_boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._render.is_slot_running",
            side_effect=_boom,
        ),
        # Chop run-history readers must never fire on navigation either.
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_index", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail", _boom),
    ):
        # Lumberjack view (hooks → top-level row 0).
        app.current_idx = 0
        app._refresh_axe_display_debounced()
        # Fire the debounced callback and verify no reader was hit.
        assert app._scheduled_callbacks, "debounce did not schedule a callback"
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()

        # Chop view: the row's parent lumberjack snapshot is cached, so
        # the dashboard repaints from memory.
        app.current_idx = 1
        app._refresh_axe_display_debounced()
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()

        # Second lumberjack view.
        app.current_idx = 2
        app._refresh_axe_display_debounced()
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()

        # Bgcmd view: cache hit means no disk readers are touched.
        app.current_idx = 3
        app._refresh_axe_display_debounced()
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()


def test_banner_follows_lumberjack_chop_generated_and_bgcmd_selection() -> None:
    """Selection repaints the fixed banner entirely from cached snapshots."""
    app = FakeAxeApp()
    app._axe_lumberjack_snapshots["hooks"].description = "Advance hook lifecycle state"
    generated = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="refresh_docs[sase]",
        description="Refresh generated documentation",
        runs=[],
        generated=True,
        base_chop_name="refresh_docs",
        target_key="sase",
    )
    app._axe_chop_snapshots[("hooks", generated.chop_name)] = generated
    app._axe_items.insert(
        2,
        ChopItem(lumberjack_name="hooks", chop_name=generated.chop_name),
    )

    dashboard = _DescriptionDashboardProbe()

    def _query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#axe-dashboard":
            return dashboard
        return MagicMock()

    app.query_one = _query_one  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.get_runner_count", return_value=0):
        app.current_idx = 0
        app._refresh_axe_display()
        assert dashboard.banner == "Advance hook lifecycle state"

        app.current_idx = 1
        app._refresh_axe_display()
        assert dashboard.banner == "fast desc"

        app.current_idx = 2
        app._refresh_axe_display()
        assert dashboard.banner == "Refresh generated documentation  · sase"

        app.current_idx = 4
        app._refresh_axe_display()
        assert dashboard.banner is None
