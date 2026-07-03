"""ACE TUI PNG visual snapshot coverage for the Models panel (leader ``,m``).

Phase 2 (epic sase-5e): pin how the new Models panel renders — the per-alias
rows with their kind badge, provider-themed ``PROVIDER(model)`` badge, and the
provenance / override state tag — in two states: the calm "no overrides" view
and an "override-active" view (a ``default`` override with a countdown plus a
non-``default`` until-cleared override).

Both the alias aggregation (:func:`build_alias_views`) and the clock (``_now``)
are pinned so the rows render identically on every run.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.llm_provider import AliasView, TemporaryLLMOverride
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03

# Frozen clock so override countdowns are deterministic.
_FROZEN_NOW = 1000.0


def _view(
    name: str,
    kind: str,
    *,
    configured: bool = False,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    override: TemporaryLLMOverride | None = None,
    configured_source: str | None = None,
    description: str | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=override,
        configured_source=configured_source,
        description=description,
    )


def _calm_views() -> list[AliasView]:
    return [
        _view(
            "default",
            "default",
            provider="claude",
            model="opus",
            description="Model used when a prompt has no %model directive.",
        ),
        _view(
            "coder",
            "role",
            configured=True,
            configured_value="@default",
            provider="claude",
            model="opus",
        ),
        _view("epic_creator", "role", provider="claude", model="opus"),
        _view(
            "phase_worker",
            "role",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
        ),
        _view("claude_coder", "provider_coder", provider="claude", model="opus"),
        _view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
        ),
        _view(
            "fast",
            "user",
            configured=True,
            configured_value="claude/haiku",
            provider="claude",
            model="haiku",
            configured_source="custom",
            description="Quick low-cost follow-up agents.",
        ),
        _view(
            "legacy_blog",
            "user",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="builtin",
        ),
    ]


def _override_views() -> list[AliasView]:
    default_override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=_FROZEN_NOW,
        expires_at=_FROZEN_NOW + 3600.0,
        source="ace",
    )
    phase_override = TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="opus",
        created_at=_FROZEN_NOW,
        expires_at=None,
        source="ace",
    )
    rows = _calm_views()
    rows[0] = _view(
        "default", "default", provider="codex", model="o3", override=default_override
    )
    rows[3] = _view(
        "phase_worker",
        "role",
        configured=True,
        configured_value="codex/o3",
        provider="claude",
        model="opus",
        override=phase_override,
    )
    return rows


async def test_models_panel_default_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _calm_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_default_120x40",
            title="ACE models panel (no overrides)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_models_panel_overrides_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _override_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_overrides_120x40",
            title="ACE models panel (overrides active)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
