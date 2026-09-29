"""ACE PNG snapshots for the Admin Tools pane (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    TOOL_RUN_EPOCH_INT,
    FakeTime,
    pin_tool_run_clocks,
    tool_run_brief,
    tool_run_glance,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _admin_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the Admin Tools pane data sources with fixed fixtures."""
    import sase.config.tools as config_tools
    from sase.ace.tui.actions.agents import _tool_run_actions as actions_module
    from sase.ace.tui.modals import tool_runs_pane_loading as pane_module
    from sase.core import tool_run as core_tool_run

    briefs = (
        tool_run_brief("6c3d5107" + "0" * 24, bucket="new_failures", new=3, known=1),
        tool_run_brief(
            "22" + "0" * 30,
            label="test",
            bucket="pass",
            agent="tr-other",
            settled_ts=TOOL_RUN_EPOCH_INT - 1500,
        ),
    )
    live = tool_run_glance("c1" + "0" * 30)
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_live_glance",
        lambda *a, **kw: SimpleNamespace(runs=[live], silent_after_s=60),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_briefs",
        lambda request: SimpleNamespace(runs=list(briefs)),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_failures",
        lambda request: {
            "groups": [
                {
                    "class": "NEW",
                    "tool": "check",
                    "stage_key": "lint (mypy)",
                    "display": "_tree.py:622 Name already defined",
                    "runs": 35,
                    "agents": 33,
                },
                {
                    "class": "KNOWN",
                    "tool": "check",
                    "stage_key": "test (scoped)",
                    "display": "test_check rerun mismatch",
                    "runs": 12,
                    "agents": 7,
                },
            ]
        },
    )
    monkeypatch.setattr(
        config_tools,
        "load_project_tool_catalog_at",
        lambda root: SimpleNamespace(
            project="sase",
            entries=[
                SimpleNamespace(name="check", digest="digest-check"),
                SimpleNamespace(name="test", digest="digest-test"),
            ],
        ),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_summary",
        lambda request: {
            "last": {"bucket": "new_failures"},
            "typical_duration_ms": 252000,
            "typical_sample_count": 41,
        },
    )
    monkeypatch.setattr(
        actions_module, "primary_checkout_root", lambda project: "/workspace/sase"
    )
    monkeypatch.setattr(pane_module, "time", FakeTime)


async def test_tool_runs_admin_pane_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_tool_run_clocks(monkeypatch)
    _admin_seams(monkeypatch)
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        page.app.screen.action_focus_center_tab(7)
        await wait_for_svg_contains(page, "Catalog")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_runs_120x40", title="ACE admin tools runs"
        )
        await page.press("right_square_bracket")
        await wait_for_svg_contains(page, "33 agents")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_failures_120x40", title="ACE admin tools failures"
        )
        await page.press("right_square_bracket")
        await wait_for_svg_contains(page, "LAST new_failures")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_catalog_120x40", title="ACE admin tools catalog"
        )
