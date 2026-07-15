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

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

import pytest
from textual.widgets import Input, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_time import OverrideUntilModal
from sase.llm_provider import AliasView, TemporaryLLMOverride
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


# Frozen clock so override countdowns are deterministic.
_FROZEN_NOW = 1000.0
_EASTERN = ZoneInfo("America/New_York")
_TIME_MODAL_NOW = datetime(2026, 7, 10, 14, 42, tzinfo=_EASTERN)


def _time_modal_clock(_timezone: tzinfo) -> datetime:
    return _TIME_MODAL_NOW


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
    bucket: str | None = None,
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
        bucket=bucket,
    )


def _calm_views() -> list[AliasView]:
    return [
        _view(
            "default",
            "default",
            provider="claude",
            model="claude-fable-4-10",
            description=(
                "Model used when a prompt has no %model directive; every other "
                "alias ultimately falls back to it."
            ),
        ),
        _view(
            "coder",
            "role",
            configured=True,
            configured_value="@default",
            provider="claude",
            model="opus",
        ),
        _view("epic_lander", "role", provider="claude", model="opus"),
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
    coder_override = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol",
        created_at=_FROZEN_NOW,
        expires_at=None,
        source="ace",
    )
    return [
        _view(
            "default",
            "default",
            provider="codex",
            model="o3",
            override=default_override,
        )
        if row.name == "default"
        else _view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="gpt-5.6-sol",
            override=coder_override,
        )
        if row.name == "codex_coder"
        else row
        for row in _calm_views()
    ]


def _bucket_views() -> list[AliasView]:
    return [
        _view(
            "default",
            "default",
            provider="claude",
            model="opus",
            description=(
                "Model used when a prompt has no %model directive; every other "
                "alias ultimately falls back to it."
            ),
        ),
        _view("coder", "role", provider="claude", model="opus"),
        _view(
            "research_a",
            "user",
            configured=True,
            configured_value="codex/gpt-5.6-sol",
            provider="codex",
            model="gpt-5.6-sol",
            configured_source="custom",
            description="Lead researcher and consolidator.",
            bucket="research",
        ),
        _view(
            "research_b",
            "user",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            configured_source="custom",
            description="Second-opinion researcher.",
            bucket="research",
        ),
        _view(
            "research_c",
            "user",
            configured=True,
            configured_value="codex/gpt-5.6-sol",
            provider="codex",
            model="gpt-5.6-sol",
            configured_source="custom",
            description="Extra researcher lane.",
            bucket="research",
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
    ]


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
        )


async def test_models_panel_coders_drilled_in_png_snapshot(
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
        await page.press("j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_coders_drilled_in_120x40",
            title="ACE models panel (coders bucket open)",
        )


async def test_models_panel_bucket_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _bucket_views()
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_bucket_120x40",
            title="ACE models panel (bucket collapsed)",
        )


async def test_models_panel_bucket_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _bucket_views()
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_bucket_drilled_in_120x40",
            title="ACE models panel (bucket open)",
        )


async def test_models_panel_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(DurationPickerModal())
        await page.expect_modal("DurationPickerModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_duration_picker_120x40",
            title="ACE model override duration picker",
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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = OverrideUntilModal(timezone=_EASTERN, clock=_time_modal_clock)
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
