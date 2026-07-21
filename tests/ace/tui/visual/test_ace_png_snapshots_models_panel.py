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
from textual.widgets import Input, OptionList, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_time import OverrideUntilModal
from sase.llm_provider import AliasView, TemporaryLLMOverride
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.load_balancing import ModelAliasSelectorMode
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
    selector_mode: ModelAliasSelectorMode | None = None,
    selector_members: tuple[ModelAliasSelectorMember, ...] = (),
    effort: str | None = None,
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
        selector_mode=selector_mode,
        selector_members=selector_members,
        effort=effort,
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
            "big_epic_lander",
            "role",
            provider="claude",
            model="opus",
            description=(
                "Epic land agents selected for plans at or above the configured "
                "phase-count threshold."
            ),
        ),
        _view(
            "small_phase_worker",
            "role",
            provider="claude",
            model="opus",
            description="Small phases that implement directly.",
        ),
        _view(
            "medium_phase_worker",
            "role",
            provider="claude",
            model="claude-fable-4-10",
            description="Medium phases that plan before implementation.",
        ),
        _view(
            "large_phase_worker",
            "role",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            description="Large phases that plan before implementation.",
        ),
        _view(
            "smartest",
            "role",
            provider="claude",
            model="claude-fable-5",
            description="Highest-capability alias for explicit use.",
            selector_mode="fallback",
            selector_members=(
                ModelAliasSelectorMember(
                    value="claude/claude-fable-5",
                    target="claude/claude-fable-5",
                    effort=None,
                    provider="claude",
                    available=True,
                    selected=True,
                ),
                ModelAliasSelectorMember(
                    value="codex/gpt-5.6-sol",
                    target="codex/gpt-5.6-sol",
                    effort=None,
                    provider="codex",
                    available=True,
                ),
            ),
        ),
        _view(
            "cheaper",
            "role",
            provider="claude",
            model="opus",
            description="Load-balanced pool used automatically by small phases.",
        ),
        _view(
            "cheapest",
            "role",
            provider="codex",
            model="gpt-5.3-codex-spark",
            description="Independent lowest-cost pool for explicit use.",
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


def _custom_builtin_warning_views() -> list[AliasView]:
    return [
        _view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
            description="Misplaced builtin coder alias.",
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


def _pool_effort_views(*, suspended: bool = False) -> list[AliasView]:
    pool_members = (
        ModelAliasSelectorMember(
            value="claude/opus@medium",
            target="claude/opus",
            effort="medium",
            provider="claude",
            available=False,
        ),
        ModelAliasSelectorMember(
            value="codex/gpt-5.5@high",
            target="codex/gpt-5.5",
            effort="high",
            provider="codex",
            available=True,
            selected=True,
        ),
    )
    pool_override = (
        TemporaryLLMOverride(
            provider="claude",
            model="sonnet",
            raw_model="claude/sonnet",
            created_at=_FROZEN_NOW,
            expires_at=None,
            source="ace",
        )
        if suspended
        else None
    )
    rows = [
        _view(
            "cheaper",
            "role",
            configured=True,
            configured_value="claude/opus@medium | codex/gpt-5.5@high",
            provider="claude" if suspended else "codex",
            model="sonnet" if suspended else "gpt-5.5",
            override=pool_override,
            configured_source="builtin",
            description="Cheap load-balanced pool for high-volume agents.",
            selector_mode="round_robin",
            selector_members=pool_members,
            effort=None if suspended else "high",
        )
        if row.name == "cheaper"
        else row
        for row in _calm_views()
    ]
    rows.append(
        _view(
            "focused",
            "user",
            configured=True,
            configured_value="claude/opus@medium",
            provider="claude",
            model="opus",
            configured_source="custom",
            description="Focused analysis with a pinned effort.",
            effort="medium",
        )
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_default_120x40",
            title="ACE models panel (no overrides)",
        )


async def test_models_panel_smartest_fallback_png_snapshot(
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_smartest_fallback_120x40",
            title="ACE models panel (ordered smartest fallback)",
        )


async def test_models_panel_pool_effort_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show the default, pool availability/next member, and row effort."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _pool_effort_views()
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_effort_120x40",
            title="ACE models panel (pool and effort)",
        )


async def test_models_panel_effort_provenance_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _pool_effort_views()
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_provenance_120x40",
            title="ACE models panel (effort provenance)",
        )


async def test_models_panel_pool_suspended_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel,
        "build_alias_views",
        lambda *a, **k: _pool_effort_views(suspended=True),
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_suspended_120x40",
            title="ACE models panel (pool suspended by override)",
        )


async def test_models_panel_alias_picker_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Models-panel Edit path shows a filtered, highlighted alias row."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: _calm_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        # default -> coders bucket -> epic_lander -> big_epic_lander ->
        # phase_worker bucket -> small member, where @coder is a safe
        # persistent reference.
        await page.press("j", "j", "j", "j", "l", "e")
        await page.expect_modal("ModelPickerModal")
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "@coder"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                picker_list.highlighted is not None
                and picker_list.get_option_at_index(picker_list.highlighted).id
                == "@coder"
            ),
            description="filtered @coder alias highlighted",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_picker_filtered_120x40",
            title="ACE models panel — filtered alias picker",
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_overrides_120x40",
            title="ACE models panel (overrides active)",
        )


async def test_models_panel_custom_builtin_warning_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel,
        "build_alias_views",
        lambda *a, **k: _custom_builtin_warning_views(),
    )
    monkeypatch.setattr(models_panel, "_now", lambda: _FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_custom_builtin_warning_120x40",
            title="ACE models panel (misplaced builtin warning)",
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_coders_drilled_in_120x40",
            title="ACE models panel (coders bucket open)",
        )


async def test_models_panel_phase_worker_drilled_in_png_snapshot(
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_phase_worker_drilled_in_120x40",
            title="ACE models panel (phase_worker bucket open)",
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
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
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
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
