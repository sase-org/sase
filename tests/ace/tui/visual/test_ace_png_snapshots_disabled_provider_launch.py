"""ACE TUI PNG snapshots for the disabled-provider launch panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.disabled_provider_launch_modal import (
    DisabledProviderLaunchModal,
)
from sase.agent.launch_guard import LaunchUnit, LaunchUnitCandidate
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    provider_disable,
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

_SINGLE_PROMPT = (
    "#gh:sase %m:opus Fix the flaky selector test in tests/ace/tui/"
    "test_disabled_provider_launch_panel.py"
)


def _candidate(
    prompt: str,
    *,
    provider: str,
    model: str,
    blocked: TemporaryProviderDisable,
) -> LaunchUnitCandidate:
    return LaunchUnitCandidate(
        slot_index=0,
        prompt=prompt,
        provider=provider,
        model=model,
        blocked_by=blocked,
        unavailable=False,
    )


def _single_unit() -> tuple[LaunchUnit, dict[str, TemporaryProviderDisable]]:
    record = provider_disable("claude", expires_at=FROZEN_NOW + 6_120.0)
    unit = LaunchUnit(
        index=1,
        total=1,
        prompt=_SINGLE_PROMPT,
        template_group=None,
        swarm_xprompts=(),
        candidates=(
            _candidate(_SINGLE_PROMPT, provider="claude", model="opus", blocked=record),
        ),
        _blocking_disables=(record,),
    )
    return unit, {record.provider: record}


def _swarm_unit() -> tuple[LaunchUnit, dict[str, TemporaryProviderDisable]]:
    claude = provider_disable("claude", expires_at=FROZEN_NOW + 6_120.0)
    codex = provider_disable(
        "codex", expires_at=FROZEN_NOW + 2_520.0, source="usage_limit"
    )
    prompt = "%model:@large Fix the flaky selector test in tests/ace/tui/"
    unit = LaunchUnit(
        index=2,
        total=4,
        prompt=prompt,
        template_group=None,
        swarm_xprompts=(),
        candidates=(
            _candidate(prompt, provider="claude", model="opus", blocked=claude),
        ),
        _blocking_disables=(claude, codex),
    )
    return unit, {claude.provider: claude, codex.provider: codex}


async def test_disabled_provider_launch_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        unit, snapshot = _single_unit()
        page.app.push_screen(
            DisabledProviderLaunchModal(unit, now=FROZEN_NOW, snapshot=snapshot)
        )
        await page.expect_modal("DisabledProviderLaunchModal")
        await wait_for_svg_contains(page, "Enable CLAUDE")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "disabled_provider_launch_panel_120x40",
            title="ACE disabled-provider launch panel",
        )


async def test_disabled_provider_launch_panel_swarm_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        unit, snapshot = _swarm_unit()
        page.app.push_screen(
            DisabledProviderLaunchModal(unit, now=FROZEN_NOW, snapshot=snapshot)
        )
        await page.expect_modal("DisabledProviderLaunchModal")
        await wait_for_svg_contains(page, "Abort all 4 agents")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "disabled_provider_launch_panel_swarm_120x40",
            title="ACE disabled-provider launch panel (swarm)",
        )


async def test_disabled_provider_launch_panel_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        unit, snapshot = _swarm_unit()
        page.app.push_screen(
            DisabledProviderLaunchModal(unit, now=FROZEN_NOW, snapshot=snapshot)
        )
        await page.expect_modal("DisabledProviderLaunchModal")
        await wait_for_svg_contains(page, "Abort all 4")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "disabled_provider_launch_panel_narrow_70x32",
            title="ACE disabled-provider launch panel (narrow)",
        )
