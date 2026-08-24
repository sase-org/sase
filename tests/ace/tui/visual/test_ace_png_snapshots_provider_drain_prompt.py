"""ACE TUI PNG snapshot for the provider-drain prompt panel."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.provider_drain_prompt_modal import ProviderDrainPromptModal
from sase.agent.provider_drain import (
    DrainRoute,
    ProviderDrainMove,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
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


def _move(
    name: str,
    *,
    target_provider: str,
    target_model: str = "gpt-5",
) -> ProviderDrainMove:
    return ProviderDrainMove(
        name=name,
        presented_name=name,
        project="sase",
        status="RUNNING",
        route=DrainRoute(
            kind="reroute",
            target_provider=target_provider,
            target_model=target_model,
        ),
        restart_plan=SimpleNamespace(),  # type: ignore[arg-type]
    )


def _plan() -> ProviderDrainPlan:
    return ProviderDrainPlan(
        provider="claude",
        disable=provider_disable("claude", expires_at=FROZEN_NOW + 6_120.0),
        moves=(
            _move("sase-aa", target_provider="codex"),
            _move("sase-bb", target_provider="codex"),
            _move("sase-cc", target_provider="gemini"),
        ),
        skips=(
            ProviderDrainSkip(
                name="sase-dd",
                presented_name="sase-dd",
                status="RUNNING",
                reason="stranded",
                detail="pinned to claude/opus; not reachable",
            ),
        ),
        model_override=None,
        limit=20,
    )


async def test_provider_drain_prompt_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ProviderDrainPromptModal(_plan(), now=FROZEN_NOW))
        await page.expect_modal("ProviderDrainPromptModal")
        await wait_for_svg_contains(page, "Relaunch 3 agents now")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "provider_drain_prompt_panel_120x40",
            title="ACE provider-drain prompt panel",
        )
