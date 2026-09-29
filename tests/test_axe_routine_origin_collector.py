"""Collector and display apply path for AXE routine origins.

The off-thread collector maps every routine/job to its declaring source,
header-only ticks carry the full maps so apply never drops origins, and
the targeted chop fast path re-reads runs without touching origins.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.axe.config import ChopConfig, LumberjackConfig
from sase.axe.config_backend import AxeEntityOrigin

pytest_plugins = ("tests._axe_routine_origin_helpers",)


def test_collector_returns_origin_maps_from_cached_config(
    reset_axe_config_cache: Any,
) -> None:
    """The off-thread collector maps every routine/job to its origin."""
    from types import SimpleNamespace

    from sase.ace.tui.actions.axe_display import collect_axe_status_data
    from sase.ace.tui.actions.axe_display._data import AxeStatusReadCache

    config = SimpleNamespace(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hooks",
                interval=60,
                source="plugin",
                declared_by="plugin:acme",
                chops=[
                    ChopConfig(
                        name="fast",
                        description="Fast job",
                        source="plugin",
                        declared_by="plugin:acme",
                    )
                ],
            )
        },
        chop_script_dirs=[],
    )
    with (
        patch(
            "sase.service.control.persisted_or_current_status",
            return_value=SimpleNamespace(
                host=SimpleNamespace(state="stopped"), procs=(), change_token=""
            ),
        ),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
    ):
        data = collect_axe_status_data(
            cache=AxeStatusReadCache(),
            include_full_snapshots=True,
            tail_chop_keys=frozenset(),
            tail_service_name=None,
        )
    assert data.lumberjack_names == ["hooks"]
    assert data.routine_origins == {
        "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert data.chop_origins == {
        ("hooks", "fast"): AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert data.lumberjack_snapshots["hooks"].source == "plugin"
    assert data.chop_snapshots[("hooks", "fast")].source == "plugin"


def test_collector_header_payload_preserves_origin_maps() -> None:
    """Header-only ticks carry full maps so apply never drops origins."""
    from sase.ace.tui.actions.axe_display import collect_axe_status_data
    from sase.ace.tui.actions.axe_display._data import AxeStatusReadCache
    from tests.ace.tui._axe_collector_helpers import (
        FakeAxeConfig,
        lumberjack_config,
        patch_service_status,
    )

    raw = lumberjack_config("hooks", ["fast"])
    raw.source = "builtin"
    raw.declared_by = "default"
    raw.chops[0].source = "builtin"
    raw.chops[0].declared_by = "default"
    config = FakeAxeConfig({"hooks": raw})
    with (
        patch_service_status(),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
    ):
        data = collect_axe_status_data(
            cache=AxeStatusReadCache(),
            include_full_snapshots=False,
            tail_chop_keys=frozenset(),
            tail_service_name=None,
        )
    assert data.lumberjack_names == ["hooks"]
    assert data.routine_origins["hooks"].source == "builtin"
    assert data.chop_origins[("hooks", "fast")].source == "builtin"


def _apply_payload(
    *,
    names: list[str],
    origins: dict[str, AxeEntityOrigin],
    chop_origins: dict[tuple[str, str], AxeEntityOrigin] | None = None,
    full: bool = True,
) -> Any:
    """Build a minimal collector payload carrying names plus origins."""
    from sase.ace.tui.actions.axe_display._data import AxeCollectedData

    return AxeCollectedData(
        axe_running=False,
        axe_output="",
        lumberjack_names=names,
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={name: [] for name in names},
        routine_origins=origins,
        chop_origins=chop_origins or {},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=full,
    )


class _ApplyFake:
    """Minimal harness driving the collector apply path without Textual."""

    def __init__(self) -> None:
        from sase.ace.tui.actions.axe_display import AxeDisplayMixin

        self._apply = AxeDisplayMixin._apply_axe_status_data
        self._settle = AxeDisplayMixin._settle_bgcmd_slots
        self._reconcile = AxeDisplayMixin._reconcile_chop_run_offsets
        self._slot_visible = AxeDisplayMixin._bgcmd_slot_visible
        self.current_tab = "services"
        self.current_idx = 0
        self.refresh_interval = 10
        self.axe_running = False
        self._countdown_remaining = 10
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view: Any = "axe"
        self._bgcmd_slots: list[Any] = []
        self._bgcmd_pending_slots: dict[Any, Any] = {}
        self._bgcmd_dismissed: set[str] = set()
        self._bgcmd_focus_slot = None
        self._axe_lumberjack_names: list[str] = []
        self._axe_routine_origins: dict[str, AxeEntityOrigin] = {}
        self._axe_chop_origins: dict[tuple[str, str], AxeEntityOrigin] = {}
        self._axe_lumberjack_idx = None
        self._axe_items: list[Any] = []
        self._axe_chop_selection = None
        self._axe_first_load_done = True
        self._axe_lumberjack_statuses: dict[str, Any] = {}
        self._axe_lumberjack_metrics: dict[str, Any] = {}
        self._axe_lumberjack_log_tails: dict[str, str] = {}
        self._axe_bgcmd_details: dict[Any, Any] = {}
        self._axe_lumberjack_chop_names: dict[str, list[str]] = {}
        self._axe_chop_snapshots: dict[Any, Any] = {}
        self._axe_chop_run_offsets: dict[Any, Any] = {}
        self._axe_lumberjack_snapshots: dict[str, Any] = {}
        self._axe_tailed_chops: set[Any] = set()
        self._axe_degraded_status = None
        self._service_status = None
        self._service_status_error = None
        self._service_log_tails: dict[str, str] = {}
        self._service_tailed_names: set[str] = set()

    # Bound-mixin helpers the apply path reaches for.
    def _set_axe_starting(self, *_a: Any) -> None:
        return None

    def _set_axe_restarting(self, *_a: Any) -> None:
        return None

    def _set_axe_stopping(self, *_a: Any) -> None:
        return None

    def _settle_bgcmd_slots(self, slots: Any) -> Any:
        return self._settle(self, slots)  # type: ignore[arg-type]

    def _bgcmd_slot_visible(self, slot: Any, info: Any) -> bool:
        return self._slot_visible(self, slot, info)  # type: ignore[arg-type]

    def _reconcile_chop_run_offsets(self, snapshots: Any) -> None:
        self._reconcile(self, snapshots)  # type: ignore[arg-type]

    def _update_axe_keybinding(self) -> None:
        return None

    def _update_bgcmd_count(self) -> None:
        return None

    def _build_axe_items(self) -> None:
        return None

    def _refresh_axe_display(self) -> None:
        return None

    def apply(self, data: Any) -> None:
        self._apply(self, data)  # type: ignore[arg-type]


def test_apply_sets_names_and_origins_atomically() -> None:
    """One collect lands names and origins together, never half-applied."""
    app = _ApplyFake()
    app.apply(
        _apply_payload(
            names=["hooks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
            },
            chop_origins={
                ("hooks", "fast"): AxeEntityOrigin(
                    source="plugin", declared_by="plugin:acme"
                )
            },
        )
    )
    assert app._axe_lumberjack_names == ["hooks"]
    assert app._axe_routine_origins == {
        "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert app._axe_chop_origins == {
        ("hooks", "fast"): AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }


def test_apply_replaces_stale_origins_on_config_change() -> None:
    """A removed routine's origin leaves with its name (header-safe)."""
    app = _ApplyFake()
    app.apply(
        _apply_payload(
            names=["hooks", "checks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme"),
                "checks": AxeEntityOrigin(source="builtin", declared_by="default"),
            },
        )
    )
    # Header-only tick after the user deletes a routine: the payload
    # carries the fresh complete maps, so no stale origin survives.
    app.apply(
        _apply_payload(
            names=["hooks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
            },
            full=False,
        )
    )
    assert app._axe_lumberjack_names == ["hooks"]
    assert set(app._axe_routine_origins) == {"hooks"}


@pytest.mark.asyncio
async def test_targeted_chop_refresh_preserves_origin() -> None:
    """The `y` fast path re-reads runs, never the chop's origin."""
    from sase.ace.tui.actions.axe_display import (
        AxeDisplayMixin,
        ChopSnapshot,
    )
    from sase.ace.tui.widgets.bgcmd_list import ChopItem, LumberjackItem

    class _TargetedFake(AxeDisplayMixin):
        def __init__(self) -> None:
            self.current_tab: Any = "services"
            self.current_idx = 1
            self._axe_current_view: Any = "axe"
            self._axe_lumberjack_names = ["hooks"]
            self._axe_lumberjack_idx = 0
            self._axe_items: list[Any] = [
                LumberjackItem(name="hooks"),
                ChopItem(lumberjack_name="hooks", chop_name="fast"),
            ]
            self._axe_chop_selection = None
            self._axe_chop_snapshots = {
                ("hooks", "fast"): ChopSnapshot(
                    lumberjack_name="hooks",
                    chop_name="fast",
                    description="",
                    runs=[],
                    source="builtin",
                    declared_by="default",
                )
            }
            self._axe_chop_run_offsets = {}
            self._axe_lumberjack_snapshots = {}
            self._axe_tailed_chops: set[Any] = set()
            self._axe_targeted_refresh_running = False
            self._axe_targeted_refresh_pending = False
            self._axe_targeted_refresh_scheduled = False

        def _refresh_axe_display(self) -> None:  # type: ignore[override]
            return None

    app = _TargetedFake()
    with patch(
        "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
        return_value=[],
    ):
        await app._refresh_selected_axe_item_async()  # type: ignore[attr-defined]
    snap = app._axe_chop_snapshots[("hooks", "fast")]
    assert snap.source == "builtin"
    assert snap.declared_by == "default"
