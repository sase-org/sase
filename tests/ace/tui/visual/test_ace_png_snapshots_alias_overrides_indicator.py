"""ACE TUI PNG visual snapshot coverage for the non-default override pill.

Phase 4 (epic sase-5e): pin how the top-bar ``AliasOverridesIndicator`` renders
temporary overrides on *non-*``default`` aliases — the concise violet pill that
sits next to the gold ``default`` pill (:class:`LLMOverrideIndicator`) in two
states:

* **single** — exactly one non-``default`` override, shown as the two-tone
  ``@<alias>@<effort> ∞`` beside the calm default-model pill;
* **multi** — several non-``default`` overrides collapsed to
  ``@<alphabetically-first-alias> +N``, shown beside an active *default*
  override pill (the "default + non-default together" case).

Both use until-cleared overrides so no live countdown leaks into the frame; the
empty state (no non-``default`` override) is the baseline pinned by every other
top-bar snapshot, so it needs no dedicated frame here.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.llm_override_indicator as llm_override_indicator
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.llm_provider import TemporaryLLMOverride, TemporaryProviderDisable
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


# Frozen creation clock; every override is until-cleared so no countdown runs.
_FROZEN_NOW = 1000.0


def _override(
    provider: str,
    model: str,
    *,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=_FROZEN_NOW,
        expires_at=None,
        source="ace",
        effort=effort,
    )


def _disable(
    provider: str,
    *,
    expires_at: float | None = None,
    mode: str = "hard",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=_FROZEN_NOW,
        expires_at=expires_at,
        source="visual",
        mode=mode,
    )


async def test_alias_overrides_indicator_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    # One non-default override; the gold default pill stays on the calm default
    # model (no default override active).
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda *a, **k: {"medium": _override("codex", "o3", effort="max")},
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "alias_overrides_indicator_single_120x40",
            title="ACE @medium@max ∞ override pill",
        )


async def test_alias_overrides_indicator_multi_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    # Several non-default overrides name the first alias and count the rest; a
    # ``default`` entry is present too (it drives the gold pill and is excluded
    # from the violet count) so the paired-lanes frame is exercised.
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda *a, **k: {
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): _override(
                "codex", "o3"
            ),
            "small": _override("claude", "opus"),
            "medium": _override("codex", "o3"),
            "fast": _override("claude", "haiku"),
        },
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "peek_active_temporary_override",
        lambda *a, **k: _override("codex", "o3"),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "alias_overrides_indicator_multi_120x40",
            title="ACE @fast +2 and default ∞ override pills",
        )


async def test_provider_disables_indicator_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_active_provider_disables",
        lambda: {"claude": _disable("claude")},
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "provider_disables_indicator_single_120x40",
            title="ACE CLAUDE disabled provider pill",
        )


async def test_provider_disables_indicator_multiple_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_active_provider_disables",
        lambda: {
            "claude": _disable("claude"),
            "codex": _disable("codex"),
            "gemini": _disable("gemini"),
        },
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "provider_disables_indicator_multiple_120x40",
            title="ACE multiple disabled provider pill",
        )


async def test_provider_disables_indicator_soft_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_active_provider_disables",
        lambda: {"claude": _disable("claude", mode="soft")},
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "provider_disables_indicator_soft_120x40",
            title="ACE CLAUDE soft-disabled provider pill",
        )
