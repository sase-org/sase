"""ACE TUI PNG snapshots for the Config Flags pane."""

from __future__ import annotations

from datetime import date

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.feature_flags_pane import FeatureFlagsPane
from sase.ace.tui.modals.feature_flags_pane_load import FeatureFlagsPaneLoad
from sase.ace.tui.modals.feature_flags_pane_rendering import ROLLOUT_FLAG_KEY
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import FeatureFlagDecision
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.feature_flags._helpers import demo_flag, flag_bead

pytestmark = pytest.mark.visual

_TODAY = date(2026, 8, 21)
_RELEASE = "0.16.0"
_STATE_PATH = "/tmp/visual-feature-flags.json"


def _view(
    key: str,
    *,
    kind: str = "beta",
    enabled: bool = False,
    source: str = "default",
    source_detail: str = "",
    saved: bool | None = None,
    due_state: str | None = None,
    description: str,
) -> FlagView:
    definition = demo_flag(key, kind=kind, description=description)  # type: ignore[arg-type]
    return FlagView(
        definition=definition,
        decision=FeatureFlagDecision(
            key=key,
            enabled=enabled,
            default=definition.default,
            source=source,  # type: ignore[arg-type]
            source_detail=source_detail,
            overridden=source != "default",
        ),
        bead=flag_bead(key, bead_id=f"sase-{key[:2]}"),
        due_state=due_state,  # type: ignore[arg-type]
        saved=saved,
    )


def _populated_payload() -> FeatureFlagsPaneLoad:
    return FeatureFlagsPaneLoad(
        views=(
            _view(
                ROLLOUT_FLAG_KEY,
                kind="sunset",
                enabled=True,
                source="default",
                description="The Config catalog exposes the Flags pane.",
            ),
            _view(
                "artifact_links",
                enabled=True,
                source="state",
                source_detail=_STATE_PATH,
                saved=True,
                description="Agents add typed artifact links between records.",
            ),
            _view(
                "epic_resume_gate",
                enabled=False,
                source="cli",
                source_detail="--disable-feature",
                saved=True,
                due_state="soon",
                description="Resume an epic from its last closed phase.",
            ),
        ),
        state_path=_STATE_PATH,
        diagnostics=(),
        today=_TODAY,
        release=_RELEASE,
    )


def _install_load(
    monkeypatch: pytest.MonkeyPatch, payload: FeatureFlagsPaneLoad
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.feature_flags_pane.load_feature_flags_pane_state",
        lambda: payload,
    )


async def _open_flags_pane(
    page: AcePage,
) -> tuple[ConfigCenterModal, FeatureFlagsPane]:
    modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="flags"))
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await wait_for_state(
        page,
        lambda: bool(modal.query("#config")),
        description="Config hub mounted",
    )
    hub = modal.query_one("#config", ConfigHubPane)
    await wait_for_state(
        page,
        lambda: hub._active_subtab == "flags" and "flags" in hub._panes,
        description="Flags pane open",
    )
    pane = modal.query_one("#flags", FeatureFlagsPane)
    await wait_for_state(
        page,
        lambda: not pane._loading,
        description="Flags pane loaded",
    )
    await wait_for_visual_idle(page)
    return modal, pane


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "config_center_flags_populated_dark_120x40",
            "ACE SASE Admin Center — Config Flags populated dark",
        ),
        (
            "textual-light",
            "config_center_flags_populated_light_120x40",
            "ACE SASE Admin Center — Config Flags populated light",
        ),
    ],
)
async def test_config_center_flags_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _install_load(monkeypatch, _populated_payload())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        await _open_flags_pane(page)
        await wait_for_svg_contains(page, "FLAGS")
        await wait_for_svg_contains(page, "artifact_links")
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_config_center_flags_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _install_load(
        monkeypatch,
        FeatureFlagsPaneLoad(
            views=(),
            state_path=_STATE_PATH,
            diagnostics=(),
            today=_TODAY,
            release=_RELEASE,
        ),
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_flags_pane(page)
        await wait_for_svg_contains(page, "No feature flags are registered")
        ace_png_visual.assert_page_png(
            page,
            "config_center_flags_empty_120x40",
            title="ACE SASE Admin Center — Config Flags empty",
        )


async def test_config_center_flags_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _install_load(monkeypatch, _populated_payload())
    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await _open_flags_pane(page)
        await wait_for_svg_contains(page, "FLAGS")
        ace_png_visual.assert_page_png(
            page,
            "config_center_flags_populated_70x32",
            title="ACE SASE Admin Center — Config Flags narrow",
        )


async def test_config_center_flags_confirm_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _install_load(monkeypatch, _populated_payload())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        _modal, pane = await _open_flags_pane(page)
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "config_center_flags_confirm_120x40",
            title="ACE SASE Admin Center — Config Flags toggle confirmation",
        )
