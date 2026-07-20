"""ACE TUI PNG visual snapshot coverage for the Axe tab.

ChangeSpecs-tab snapshots live in ``test_ace_png_snapshots`` and Agents-tab
snapshots in ``test_ace_png_snapshots_agents*``. Shared fixtures live in
``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    axe_collected_data,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _axe_bgcmd_fixture() -> AxeCollectedData:
    info_a = BackgroundCommandInfo(
        command="just test --visual",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-05-09T10:00:00",
        pid=12345,
    )
    info_b = BackgroundCommandInfo(
        command="just check",
        project="visual_project",
        workspace_num=2,
        workspace_dir="/workspace/sase_2",
        started_at="2026-05-09T10:05:00",
        pid=None,
        finished_at="2026-05-09T10:09:00",
    )
    slots = [(1, info_a), (2, info_b)]
    details = {
        1: BgCmdSnapshot(info=info_a, running=True, output_tail="running tests..."),
        2: BgCmdSnapshot(info=info_b, running=False, output_tail="check passed"),
    }
    return axe_collected_data(bgcmd_slots=slots, bgcmd_details=details)


async def test_axe_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, axe_data=_axe_bgcmd_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.press("j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_selected_row_120x40",
            title="ACE axe selected row",
        )


def _make_lumberjack_status(
    name: str, status: str = "running", chops: list[str] | None = None
) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status=status,  # type: ignore[arg-type]
        interval=60,
        chops=list(chops or []),
        last_cycle="2026-05-09T10:05:00",
        cycles_run=12,
        errors_encountered=0,
        uptime_seconds=300,
    )


def _make_chop_run(
    lumberjack: str,
    chop: str,
    *,
    run_id: str,
    status: str,
) -> ChopRunSnapshot:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-09T10:00:00",
        finished_at="2026-05-09T10:00:01",
        duration_ms=1000,
        status=status,  # type: ignore[arg-type]
        exit_code=0 if status == "success" else 1,
        output_bytes=64,
        output_log=f"{run_id}.log",
    )
    return ChopRunSnapshot(entry=entry, output_tail=f"{chop} {status} output\n")


def _axe_lumberjack_tree_fixture() -> AxeCollectedData:
    """Fixture covering lumberjacks with chops alongside a bgcmd row."""
    hooks_fast = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="fast lint",
        runs=[
            _make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100100_000000",
                status="success",
            ),
        ],
    )
    hooks_slow = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="slow typecheck",
        runs=[
            _make_chop_run(
                "hooks",
                "slow_typecheck",
                run_id="20260509T100000_000000",
                status="failure",
            ),
        ],
    )
    checks_smoke = ChopSnapshot(
        lumberjack_name="checks",
        chop_name="smoke",
        description="smoke",
        runs=[],
    )
    chop_snapshots = {
        ("hooks", "fast_lint"): hooks_fast,
        ("hooks", "slow_typecheck"): hooks_slow,
        ("checks", "smoke"): checks_smoke,
    }
    hooks_status = _make_lumberjack_status(
        "hooks", chops=["fast_lint", "slow_typecheck"]
    )
    checks_status = _make_lumberjack_status("checks", status="stopped", chops=["smoke"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=1
    )
    lumberjack_snapshots = {
        "hooks": LumberjackSnapshot(
            name="hooks",
            status=hooks_status,
            metrics=metrics,
            log_tail="",
            chops=[hooks_fast, hooks_slow],
        ),
        "checks": LumberjackSnapshot(
            name="checks",
            status=checks_status,
            metrics=metrics,
            log_tail="",
            chops=[checks_smoke],
        ),
    }
    bgcmd_info = BackgroundCommandInfo(
        command="just check",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-05-09T10:05:00",
        pid=12345,
    )
    return axe_collected_data(
        lumberjack_names=["hooks", "checks"],
        lumberjack_statuses={"hooks": hooks_status, "checks": checks_status},
        lumberjack_metrics={"hooks": metrics, "checks": metrics},
        lumberjack_log_tails={"hooks": "", "checks": ""},
        lumberjack_chop_names={
            "hooks": ["fast_lint", "slow_typecheck"],
            "checks": ["smoke"],
        },
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
        bgcmd_slots=[(1, bgcmd_info)],
        bgcmd_details={
            1: BgCmdSnapshot(info=bgcmd_info, running=True, output_tail="building...")
        },
    )


async def test_axe_lumberjack_tree_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lumberjack tree with expanded chops and a bgcmd row below."""
    patch_startup_loaders(monkeypatch, axe_data=_axe_lumberjack_tree_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_lumberjack_tree_120x40",
            title="ACE axe lumberjack tree",
        )


async def test_axe_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AXE tab with no lumberjacks and no bgcmds (empty-state placeholder)."""
    patch_startup_loaders(monkeypatch, axe_data=axe_collected_data())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_empty_120x40",
            title="ACE axe empty",
        )


async def test_axe_chop_run_info_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop row selected → chop-run-detail view exercises update_chop_status."""
    from sase.ace.tui.widgets.bgcmd_list import ChopItem

    patch_startup_loaders(monkeypatch, axe_data=_axe_lumberjack_tree_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items are: [hooks LJ, hooks/fast_lint chop, hooks/slow_typecheck chop,
        # checks LJ, checks/smoke chop, bgcmd slot 1]. Two j presses from the
        # default idx=0 lands on hooks/slow_typecheck (the chop with a
        # failure run + non-empty output_tail).
        await page.press("j")
        await page.press("j")
        assert page.app.current_idx == 2, (
            f"expected idx 2 (hooks/slow_typecheck), got {page.app.current_idx}"
        )
        selected = page.app._axe_items[page.app.current_idx]
        assert isinstance(selected, ChopItem), (
            f"expected ChopItem at idx 2, got {type(selected).__name__}"
        )
        assert (selected.lumberjack_name, selected.chop_name) == (
            "hooks",
            "slow_typecheck",
        )
        # j-navigation routes the dashboard repaint through a 0.15s debouncer;
        # force the chop-run-detail view to render before snapshotting so the
        # output panel reflects the new selection rather than the idx=0
        # lumberjack overview.
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_run_info_panel_120x40",
            title="ACE axe chop run info panel",
        )


def _axe_lumberjack_error_fixture() -> AxeCollectedData:
    """Single lumberjack in error state with one failing chop run."""
    failed_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="fast lint",
        runs=[
            _make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100000_000000",
                status="failure",
            ),
        ],
    )
    error_status = LumberjackStatus(
        name="hooks",
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status="error",
        interval=60,
        chops=["fast_lint"],
        last_cycle="2026-05-09T10:05:00",
        cycles_run=5,
        errors_encountered=3,
        uptime_seconds=300,
    )
    metrics = LumberjackMetrics(
        cycles_run=5, chops_executed=5, total_updates=2, errors_encountered=3
    )
    log_tail = "ERROR: hooks crashed at cycle 5"
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": error_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": log_tail},
        lumberjack_chop_names={"hooks": ["fast_lint"]},
        chop_snapshots={("hooks", "fast_lint"): failed_chop},
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=error_status,
                metrics=metrics,
                log_tail=log_tail,
                chops=[failed_chop],
            ),
        },
    )


async def test_axe_lumberjack_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errored lumberjack exercises red/warning styling in tree row + panel."""
    patch_startup_loaders(monkeypatch, axe_data=_axe_lumberjack_error_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_lumberjack_error_120x40",
            title="ACE axe lumberjack error",
        )


def _axe_running_chop_fixture() -> AxeCollectedData:
    """Fixture with an in-flight manual chop run streaming its output."""
    # Naive ISO timestamps make _format_relative_time / _format_runtime
    # return the deterministic "unknown" fallback (they require tz-aware
    # input), so the rendered "Elapsed"/"When" cells stay stable across runs.
    live_entry = ChopRunEntry(
        run_id="20260509T100200_000000",
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        started_at="2026-05-09T10:02:00",
        finished_at=None,
        duration_ms=0,
        status="running",  # type: ignore[arg-type]
        exit_code=None,
        pid=98765,
        output_bytes=42,
        output_log="20260509T100200_000000.log",
        source="manual",  # type: ignore[arg-type]
    )
    live_run = ChopRunSnapshot(
        entry=live_entry,
        output_tail="checking module foo...\nchecking module bar...\n",
    )
    hooks_slow = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="slow typecheck",
        runs=[live_run],
    )
    chop_snapshots = {("hooks", "slow_typecheck"): hooks_slow}
    hooks_status = _make_lumberjack_status("hooks", chops=["slow_typecheck"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    lumberjack_snapshots = {
        "hooks": LumberjackSnapshot(
            name="hooks",
            status=hooks_status,
            metrics=metrics,
            log_tail="",
            chops=[hooks_slow],
        ),
    }
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["slow_typecheck"]},
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
    )


async def test_axe_chop_run_info_panel_running_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop detail view for an in-flight manual run: ● running + Source: manual."""
    from sase.ace.tui.widgets.bgcmd_list import ChopItem

    patch_startup_loaders(monkeypatch, axe_data=_axe_running_chop_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items: [hooks LJ, hooks/slow_typecheck chop]. j lands on the chop.
        await page.press("j")
        assert page.app.current_idx == 1, (
            f"expected idx 1 (hooks/slow_typecheck), got {page.app.current_idx}"
        )
        selected = page.app._axe_items[page.app.current_idx]
        assert isinstance(selected, ChopItem), (
            f"expected ChopItem at idx 1, got {type(selected).__name__}"
        )
        # Force the chop-run-detail view to render past the debouncer.
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_run_info_panel_running_120x40",
            title="ACE axe chop run info panel (running)",
        )


def _axe_long_label_fixture() -> AxeCollectedData:
    """Fixture with extra-long lumberjack/chop names to widen the sidebar.

    Phase 5 of the AXE visual redesign promises the sidebar grows to fit the
    widest formatted row. This fixture provides labels long enough to push the
    natural sidebar width well past the 35-cell minimum so the snapshot proves
    dynamic widening rather than wrapping.
    """
    chop_name = "review_pipeline_blocking_typecheck_long"
    lumberjack_name = "review_pipeline_blocking_long_name"
    chop = ChopSnapshot(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        description="long-named typecheck chop",
        runs=[
            _make_chop_run(
                lumberjack_name,
                chop_name,
                run_id="20260509T100100_000000",
                status="success",
            ),
        ],
    )
    status = _make_lumberjack_status(lumberjack_name, chops=[chop_name])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    bgcmd_info = BackgroundCommandInfo(
        command="just test --visual --snapshot --update --strict --verbose",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-05-09T10:05:00",
        pid=12345,
    )
    return axe_collected_data(
        lumberjack_names=[lumberjack_name],
        lumberjack_statuses={lumberjack_name: status},
        lumberjack_metrics={lumberjack_name: metrics},
        lumberjack_log_tails={lumberjack_name: ""},
        lumberjack_chop_names={lumberjack_name: [chop_name]},
        chop_snapshots={(lumberjack_name, chop_name): chop},
        lumberjack_snapshots={
            lumberjack_name: LumberjackSnapshot(
                name=lumberjack_name,
                status=status,
                metrics=metrics,
                log_tail="",
                chops=[chop],
            ),
        },
        bgcmd_slots=[(1, bgcmd_info)],
        bgcmd_details={
            1: BgCmdSnapshot(
                info=bgcmd_info, running=True, output_tail="running tests..."
            )
        },
    )


async def test_axe_long_label_widening_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long lumberjack/chop labels widen the sidebar without wrapping."""
    from sase.ace.tui.app import _MIN_BGCMD_LIST_WIDTH

    patch_startup_loaders(monkeypatch, axe_data=_axe_long_label_fixture())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")

        sidebar = page.app.query_one("#bgcmd-list-container")
        width = sidebar.styles.width
        assert width is not None, "expected sidebar to have a width set"
        sidebar_width = int(width.value)
        assert sidebar_width > _MIN_BGCMD_LIST_WIDTH, (
            f"expected sidebar to widen past {_MIN_BGCMD_LIST_WIDTH}, "
            f"got {sidebar_width}"
        )
        # The AXE footer repaint can lag the tab change under xdist; settle
        # only the footer so the dashboard golden stays focused on layout.
        from sase.ace.tui.widgets import KeybindingFooter

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        footer.update_axe_bindings(axe_current_view=page.app._axe_current_view)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_long_label_widened_120x40",
            title="ACE axe long-label widened sidebar",
        )


async def test_axe_constrained_width_no_wrap_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Narrow terminal with long labels proves no-wrap + ellipsis behavior."""
    patch_startup_loaders(monkeypatch, axe_data=_axe_long_label_fixture())

    # 60x30 is small enough that the sidebar gets clamped to its minimum and
    # the long lumberjack/chop labels can't fit — they must ellipsize on a
    # single line rather than wrap.
    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.expect_screen_not_contains("IDLE")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_constrained_width_no_wrap_60x30",
            title="ACE axe constrained width no-wrap",
        )
