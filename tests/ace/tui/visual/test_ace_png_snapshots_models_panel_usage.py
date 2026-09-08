"""ACE TUI PNG snapshots for the Providers · Usage view at 120/80/60 columns."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel_usage_modal as usage_modal
from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_usage_modal import ProviderUsageModal
from sase.ace.tui.modals.models_panel_usage_state import ProviderUsageViewSnapshot
from tests._usage_view_helpers import (
    FROZEN_NOW,
    usage_provider,
    usage_view_snapshot,
    usage_window,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _snapshot() -> ProviderUsageViewSnapshot:
    codex = usage_provider(
        "codex",
        plan="Plus",
        account_mode="chatgpt",
        used_percent=87.5,
        remaining_percent=12.5,
        windows=[
            usage_window(
                key="shared",
                label="Shared 5h",
                used_percent=87.5,
                remaining_percent=12.5,
                vendor_state="warning",
                freshness="fresh",
            ),
            usage_window(
                key="weekly",
                label="Weekly",
                used_percent=40.0,
                remaining_percent=60.0,
                vendor_state="allowed",
                freshness="stale",
                applicability={"kind": "account"},
                resets_at=FROZEN_NOW + 86_400.0,
            ),
        ],
    )
    grok = usage_provider(
        "grok",
        plan=None,
        account_mode=None,
        used_percent=100.0,
        remaining_percent=0.0,
        collection_status="ok",
        scope={"kind": "account"},
        windows=[
            usage_window(
                key="weekly",
                label="Weekly",
                used_percent=100.0,
                remaining_percent=0.0,
                vendor_state="rejected",
                applicability={"kind": "account"},
                resets_at=FROZEN_NOW + 3_600.0,
            )
        ],
        attention={"kind": "rejected"},
    )
    return usage_view_snapshot(codex, grok, captured_at=FROZEN_NOW)


async def _open_usage_view(page: AcePage) -> None:
    snapshot = _snapshot()

    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot))
    await page.expect_modal("ProviderUsageModal")
    await page.press("down")
    await wait_for_visual_idle(page)


async def test_models_panel_usage_120_columns_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(usage_modal, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await _open_usage_view(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_usage_120x40",
            title="ACE Providers - Usage view at 120 columns",
        )


async def test_models_panel_usage_80_columns_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(usage_modal, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 32)) as page:
        await _open_usage_view(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_usage_80x32",
            title="ACE Providers - Usage view at 80 columns",
        )


async def test_models_panel_usage_60_columns_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(usage_modal, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches(), size=(60, 32)) as page:
        await _open_usage_view(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_usage_60x32",
            title="ACE Providers - Usage view at 60 columns",
        )
