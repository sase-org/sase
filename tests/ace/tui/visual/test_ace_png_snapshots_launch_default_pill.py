"""sase's TUI PNG visual snapshot coverage for the provider-toned launch-default pill.

The calm status-row launch-default pill paints its ``<model>[@<effort>]`` label in
the hue family of the provider behind the current launch default. These two
80x24 goldens pin the default to two providers whose hues read most distinctly
(Claude amber, Grok cyan) so the frames are the visual proof that the pill's
color actually differs on screen while its glyphs and width stay identical.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.launch_context_source as launch_context_source
from sase.ace.testing import AcePage
from sase.ace.tui.widgets import LLMOverrideIndicator
from sase.llm_provider.model_launch_settings import (
    LaunchModelSettingSnapshot,
    launch_model_setting_override_key,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._provider_usage_indicator_fixtures import quiet_top_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _pin_launch_default(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str,
    model: str,
    effort: str,
) -> None:
    """Pin the resolved launch default (and its pill label) to one provider."""

    def _snapshot(
        field: object, *_args: object, **_kwargs: object
    ) -> LaunchModelSettingSnapshot:
        return LaunchModelSettingSnapshot(
            field=field,  # type: ignore[arg-type]
            config_path=f"llm_provider.{field}",
            raw_value=f"{provider}/{model}",
            provider=provider,
            model=model,
            effort=effort,
            provenance="shipped",
            referenced_alias=None,
            override_key=launch_model_setting_override_key(field),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        launch_context_source, "build_launch_model_setting_snapshot", _snapshot
    )
    # Pinned so the goldens do not depend on which provider plugins the
    # capturing host has installed.
    monkeypatch.setattr(
        launch_context_source,
        "format_model_directive_label",
        lambda *_args, **_kwargs: model,
    )


async def _capture_pill(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str,
    model: str,
    effort: str,
    name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)
    _pin_launch_default(
        monkeypatch,
        provider=provider,
        model=model,
        effort=effort,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(80, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        # The two-tone pill is two SVG text runs, so wait on the widget's own
        # resolved content rather than a contiguous frame sentinel.
        indicator = page.app.query(LLMOverrideIndicator).first()
        await wait_for_state(
            page,
            lambda: (
                indicator._build_cached_default_content().plain == f"{model}@{effort}"
            ),
            description=f"resolved launch-default pill {model}@{effort}",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, name, title=title)


async def test_launch_default_pill_claude_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_pill(
        ace_png_visual,
        monkeypatch,
        provider="claude",
        model="opus-5",
        effort="high",
        name="launch_default_pill_claude_80x24",
        title="ACE launch-default pill toned for a Claude default",
    )


async def test_launch_default_pill_grok_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_pill(
        ace_png_visual,
        monkeypatch,
        provider="grok",
        model="grok-4.6",
        effort="high",
        name="launch_default_pill_grok_80x24",
        title="ACE launch-default pill toned for a Grok default",
    )
