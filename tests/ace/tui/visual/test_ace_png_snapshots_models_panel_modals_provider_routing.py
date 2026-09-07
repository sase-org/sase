"""ACE TUI PNG snapshots for the Launch Control provider routing modal."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
import sase.ace.tui.modals.models_panel_provider_modal as models_panel_provider_modal
from sase.llm_provider.load_balancing import MemberAvailability
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    provider_disable,
    provider_priority,
    provider_status,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_models_panel_provider_routing_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable(
        "codex", expires_at=FROZEN_NOW + 2_520.0, source="usage_limit"
    )
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall"),
            ),
            provider_status("claude", model_count=11),
            provider_status("gemini", model_count=2, cli_available=False),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "Provider Routing")
        await wait_for_svg_contains(page, "disabled · usage-limit automatic · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_modal_120x40",
            title="ACE Launch Control — provider routing modal",
        )


async def test_models_panel_provider_priority_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    priority = provider_priority("codex")
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                priority=priority,
                provenance=("priority",),
            ),
            provider_status(
                "claude",
                model_count=11,
                availability=MemberAvailability.SPARING,
                priority=priority,
                provenance=("priority_backup",),
            ),
            provider_status("gemini", model_count=2, cli_available=False),
        ),
        provider_disables={},
        provider_priority=priority,
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "★ CODEX priority")
        await wait_for_svg_contains(page, "backup · CODEX priority")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_priority_modal_120x40",
            title="ACE Launch Control — provider priority modal",
        )


async def test_models_panel_provider_priority_until_cleared_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    priority = provider_priority("codex", expires_at=None)
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                priority=priority,
                provenance=("priority",),
            ),
            provider_status(
                "claude",
                model_count=11,
                availability=MemberAvailability.SPARING,
                priority=priority,
                provenance=("priority_backup",),
            ),
        ),
        provider_disables={},
        provider_priority=priority,
        alias_views=(),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "★ priority · until cleared")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_priority_until_cleared_120x40",
            title="ACE Launch Control — provider priority until cleared",
        )


async def test_models_panel_provider_priority_unavailable_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable("codex", expires_at=FROZEN_NOW + 2_520.0)
    priority = provider_priority("codex")
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                availability=MemberAvailability.UNAVAILABLE,
                priority=priority,
                provenance=("actual_hard_disable", "priority"),
            ),
            provider_status(
                "claude",
                model_count=11,
                availability=MemberAvailability.SPARING,
                priority=priority,
                provenance=("priority_backup",),
            ),
        ),
        provider_disables={"codex": disable},
        provider_priority=priority,
        alias_views=(),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "priority intent remains")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_priority_unavailable_120x40",
            title="ACE Launch Control — unavailable provider priority",
        )


async def test_models_panel_provider_routing_until_cleared_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable("codex", expires_at=None)
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall", "legacy_blog"),
            ),
            provider_status("claude", model_count=11),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "disabled · manual · until cleared")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_until_cleared_120x40",
            title="ACE Launch Control — provider routing until cleared",
        )


async def test_models_panel_provider_priority_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    priority = provider_priority("codex")
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                priority=priority,
                provenance=("priority",),
            ),
            provider_status(
                "claude",
                model_count=11,
                availability=MemberAvailability.SPARING,
                priority=priority,
                provenance=("priority_backup",),
            ),
            provider_status("gemini", model_count=2, cli_available=False),
            provider_status("opencode", model_count=3),
        ),
        provider_disables={},
        provider_priority=priority,
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
            "opencode": "#B48EAD",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "★ CODEX priority")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_priority_modal_narrow_70x32",
            title="ACE Launch Control — narrow provider priority modal",
        )


async def test_models_panel_provider_routing_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable("codex", expires_at=FROZEN_NOW + 2_520.0)
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall"),
            ),
            provider_status("claude", model_count=11),
            provider_status("gemini", model_count=2, cli_available=False),
            provider_status("opencode", model_count=3),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
            "opencode": "#B48EAD",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "Provider Routing")
        await wait_for_svg_contains(page, "disabled · manual · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_modal_narrow_70x32",
            title="ACE Launch Control — narrow provider routing modal",
        )
