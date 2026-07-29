"""Phase 5: Ctrl+N / Ctrl+P run-history navigation on the AXE tab."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.actions.axe_display import (
    AxeDisplayMixin,
    BgCmdSnapshot,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.actions.axe_display._render import _chop_allows_auto_scroll
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
)
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus


def _entry(run_id: str) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-04-23T00:00:00",
        finished_at="2026-04-23T00:00:01",
        duration_ms=1000,
        status="success",
    )


def _make_runs(*run_ids: str) -> list[ChopRunSnapshot]:
    return [ChopRunSnapshot(entry=_entry(rid), output_tail="") for rid in run_ids]


def _status(name: str) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=1,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=60,
    )


class _Fake(AxeDisplayMixin, AgentPanelDetailMixin):
    """Minimal AXE-tab harness for Ctrl+N / Ctrl+P unit tests."""

    def __init__(self, runs: list[ChopRunSnapshot]) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 1  # ChopItem
        self.refresh_interval = 10
        self.axe_running = True
        self._countdown_remaining = 10
        self._axe_status = None
        self._axe_metrics = None
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view = "axe"
        self._bgcmd_slots: list[Any] = []
        self._axe_lumberjack_names = ["hooks"]
        self._axe_lumberjack_idx = 0
        self._axe_items = [
            LumberjackItem(name="hooks"),
            ChopItem(lumberjack_name="hooks", chop_name="fast"),
            BgCmdItem(slot=1),
        ]
        self._axe_chop_selection: tuple[str, str] | None = ("hooks", "fast")
        self._bang_mode_active = False
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._axe_first_load_done = True
        self._axe_lumberjack_statuses = {"hooks": _status("hooks")}
        self._axe_lumberjack_metrics = {"hooks": LumberjackMetrics(chops_executed=3)}
        self._axe_lumberjack_log_tails = {"hooks": ""}
        self._axe_bgcmd_details: dict[int, BgCmdSnapshot] = {}
        self._axe_lumberjack_chop_names = {"hooks": ["fast"]}
        self._axe_chop_snapshots = {
            ("hooks", "fast"): ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="fast",
                description="",
                runs=runs,
            ),
        }
        self._axe_lumberjack_snapshots = {
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=_status("hooks"),
                metrics=LumberjackMetrics(chops_executed=3),
                log_tail="",
                chops=[self._axe_chop_snapshots[("hooks", "fast")]],
            ),
        }
        self._axe_chop_run_offsets: dict[tuple[str, str], int] = {}
        self._axe_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.refresh_calls = 0

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self.refresh_calls += 1

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return MagicMock()

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)


def test_default_offset_is_newest() -> None:
    app = _Fake(_make_runs("r3", "r2", "r1"))
    assert app._axe_resolve_chop_run_offset(("hooks", "fast")) == 0


def test_only_active_selected_chop_runs_allow_auto_scroll() -> None:
    terminal = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="",
        runs=_make_runs("terminal"),
    )
    active_runs = _make_runs("live")
    active_runs[0].entry.status = "running"
    active_runs[0].entry.finished_at = None
    active = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="",
        runs=active_runs,
    )

    assert not _chop_allows_auto_scroll(terminal, 0)
    assert _chop_allows_auto_scroll(active, 0)


def test_ctrl_n_advances_to_next_older_run() -> None:
    app = _Fake(_make_runs("r3", "r2", "r1"))
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 1
    assert app._axe_resolve_chop_run_offset(("hooks", "fast")) == 1
    assert app.refresh_calls == 1


def test_ctrl_p_walks_back_toward_newest() -> None:
    app = _Fake(_make_runs("r3", "r2", "r1"))
    app.action_next_agent_file()
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 2
    app.action_prev_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 1


def test_ctrl_p_at_newest_drops_pin() -> None:
    app = _Fake(_make_runs("r3", "r2", "r1"))
    app.action_next_agent_file()
    app.action_prev_agent_file()
    # Stepping back to offset 0 removes the pin so future newer runs auto-track.
    assert ("hooks", "fast") not in app._axe_chop_run_offsets


def test_offset_clamps_to_history_length() -> None:
    app = _Fake(_make_runs("r2", "r1"))
    # Press Ctrl+N way past the end → clamps at 1, no further movement.
    for _ in range(10):
        app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 1


def test_max_history_cap_clamps_offset() -> None:
    # 12 runs on disk → cap at MAX_CHOP_RUN_HISTORY (10) → max offset is 9.
    app = _Fake(_make_runs(*[f"r{i}" for i in range(12)]))
    for _ in range(20):
        app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 9


def test_no_runs_is_a_noop() -> None:
    app = _Fake(_make_runs())
    app.action_next_agent_file()
    app.action_prev_agent_file()
    assert ("hooks", "fast") not in app._axe_chop_run_offsets
    assert app.refresh_calls == 0


def test_single_run_is_a_noop() -> None:
    app = _Fake(_make_runs("r1"))
    app.action_next_agent_file()
    app.action_prev_agent_file()
    assert ("hooks", "fast") not in app._axe_chop_run_offsets
    assert app.refresh_calls == 0


def test_per_chop_offset_isolation() -> None:
    """Two chops keep independent run-history offsets."""
    app = _Fake(_make_runs("r3", "r2", "r1"))
    app._axe_lumberjack_chop_names = {"hooks": ["fast", "slow"]}
    app._axe_chop_snapshots[("hooks", "slow")] = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow",
        description="",
        runs=_make_runs("s3", "s2"),
    )
    app._axe_items.insert(2, ChopItem(lumberjack_name="hooks", chop_name="slow"))

    # Step the fast chop twice.
    app.action_next_agent_file()
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 2

    # Switch selection to the slow chop and step once.
    app.current_idx = 2
    app._axe_chop_selection = ("hooks", "slow")
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "slow")] == 1
    # Fast chop's offset is untouched.
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 2


def test_lumberjack_row_ignores_ctrl_n() -> None:
    app = _Fake(_make_runs("r2", "r1"))
    app.current_idx = 0
    app._axe_chop_selection = None
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets == {}
    assert app.refresh_calls == 0


def test_bgcmd_row_ignores_ctrl_n() -> None:
    app = _Fake(_make_runs("r2", "r1"))
    app.current_idx = 2  # BgCmdItem
    app._axe_chop_selection = None
    app.action_next_agent_file()
    assert app._axe_chop_run_offsets == {}
    assert app.refresh_calls == 0


def test_navigation_does_not_read_disk() -> None:
    """Ctrl+N / Ctrl+P repaints from cache only; no chop-run readers fire."""
    app = _Fake(_make_runs("r3", "r2", "r1"))

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("Ctrl+N / Ctrl+P must not hit disk")

    with (
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_index", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail", _boom),
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
    ):
        app.action_next_agent_file()
        app.action_next_agent_file()
        app.action_prev_agent_file()


def test_footer_surfaces_chop_run_keys_when_multiple_runs() -> None:
    """Ctrl+N / Ctrl+P appears in the footer only on chop rows with ≥2 runs."""
    from sase.ace.tui.widgets import KeybindingFooter

    footer = KeybindingFooter()
    # 2+ runs → binding shown.
    bindings = footer._compute_axe_bindings("axe", chop_run_total=3)
    assert any("chop run" == label for _, label in bindings)
    # 1 run or none → not shown.
    assert not any(
        "chop run" == label
        for _, label in footer._compute_axe_bindings("axe", chop_run_total=1)
    )
    assert not any(
        "chop run" == label
        for _, label in footer._compute_axe_bindings("axe", chop_run_total=0)
    )
    # Bgcmd row → not shown.
    assert not any(
        "chop run" == label
        for _, label in footer._compute_axe_bindings(1, chop_run_total=3)
    )


def test_footer_surfaces_edit_output_when_chop_has_run() -> None:
    """The AXE footer shows ``e`` only on chop rows with recorded output."""
    from sase.ace.tui.widgets import KeybindingFooter

    footer = KeybindingFooter()
    bindings = footer._compute_axe_bindings(
        "axe",
        chop_selected=True,
        chop_run_total=1,
    )
    assert any("edit output" == label for _, label in bindings)
    assert not any(
        "edit output" == label
        for _, label in footer._compute_axe_bindings(
            "axe",
            chop_selected=True,
            chop_run_total=0,
        )
    )
    assert not any(
        "edit output" == label
        for _, label in footer._compute_axe_bindings(
            "axe",
            chop_selected=False,
            chop_run_total=1,
        )
    )


def test_resolve_after_history_shrinks() -> None:
    """If a chop's history shrinks below the pinned offset, render clamps."""
    app = _Fake(_make_runs("r5", "r4", "r3", "r2", "r1"))
    # Pin to offset 4.
    for _ in range(4):
        app.action_next_agent_file()
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 4

    # History shrinks to 2 entries (pruning, config change, etc.).
    app._axe_chop_snapshots[("hooks", "fast")] = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="",
        runs=_make_runs("r5", "r4"),
    )
    # Resolved offset is clamped to (history_len - 1) for rendering.
    assert app._axe_resolve_chop_run_offset(("hooks", "fast")) == 1
