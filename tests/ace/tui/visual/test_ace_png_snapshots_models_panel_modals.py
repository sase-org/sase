"""ACE TUI PNG snapshots for Launch Control duration modals."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortActionModal,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_runner_limit_cards import (
    RunnerLimitActionModal,
    RunnerLimitValueModal,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_rendering import provider_duration_modal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
import sase.ace.tui.modals.models_panel_provider_modal as models_panel_provider_modal
from sase.ace.tui.modals.models_panel_time import OverrideUntilModal
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    EASTERN,
    FROZEN_NOW,
    effort_snapshot,
    provider_disable,
    provider_status,
    runner_limit_snapshot,
    time_modal_clock,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_models_panel_default_effort_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortActionModal(
                effort_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("DefaultEffortActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_action_120x40",
            title="ACE Launch Control — default-effort action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title"),
    [
        (
            "edit",
            "models_panel_effort_level_edit_120x40",
            "ACE Launch Control — persistent effort-level picker",
        ),
        (
            "override",
            "models_panel_effort_level_override_120x40",
            "ACE Launch Control — temporary effort-level picker",
        ),
    ],
)
async def test_models_panel_default_effort_level_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortLevelModal(  # type: ignore[arg-type]
                mode, effort_snapshot(), now=FROZEN_NOW
            )
        )
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_models_panel_runner_limit_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitActionModal(
                runner_limit_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("RunnerLimitActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_action_120x40",
            title="ACE Launch Control — runner-limit action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title", "initial"),
    [
        (
            "edit",
            "models_panel_runner_limit_value_edit_120x40",
            "ACE Launch Control — persistent runner-limit editor",
            10,
        ),
        (
            "override",
            "models_panel_runner_limit_value_override_120x40",
            "ACE Launch Control — temporary runner-limit editor",
            4,
        ),
    ],
)
async def test_models_panel_runner_limit_value_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
    initial: int,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitValueModal(mode, initial=initial)  # type: ignore[arg-type]
        )
        await page.expect_modal("RunnerLimitValueModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_models_panel_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(DurationPickerModal())
        await page.expect_modal("DurationPickerModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_duration_picker_120x40",
            title="ACE model override duration picker",
        )


async def test_models_panel_provider_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(provider_duration_modal("claude"))
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Disable CLAUDE")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_duration_picker_120x40",
            title="ACE provider-disable duration picker",
        )


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
        await page.press("2")
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
        await page.press("2")
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
        await page.press("2")
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


@pytest.mark.parametrize(
    ("value", "snapshot_name", "title"),
    [
        ("", "models_panel_until_neutral_120x40", "ACE override until (neutral)"),
        ("5pm", "models_panel_until_valid_120x40", "ACE override until (valid)"),
        (
            "today 1pm",
            "models_panel_until_error_120x40",
            "ACE override until (error)",
        ),
    ],
)
async def test_models_panel_override_until_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        modal = OverrideUntilModal(timezone=EASTERN, clock=time_modal_clock)
        page.app.push_screen(modal)
        await page.expect_modal("OverrideUntilModal")
        await wait_for_svg_contains(page, "Override Until")
        field = modal.query_one("#override-until-input", Input)
        if value:
            field.value = value
        expected_class = {
            "": "until-neutral",
            "5pm": "until-valid",
            "today 1pm": "until-error",
        }[value]
        preview = modal.query_one("#override-until-preview", Static)
        await wait_for_state(
            page,
            lambda: (
                field.has_focus
                and field.value == value
                and preview.has_class(expected_class)
            ),
            description=f"override-until {expected_class} preview",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
