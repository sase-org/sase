"""Tests for the status-row launch-context cluster (epic sase-14y, phase 2)."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.provider_styles import provider_text_palette
from sase.ace.tui.widgets import (
    CurrentProjectIndicator,
    LaunchContextBar,
    LLMOverrideIndicator,
)
from sase.ace.tui.widgets.launch_context_bar import (
    _choose_launch_context_density as choose_launch_context_density,
)
from sase.ace.tui.widgets.launch_context_source import (
    CurrentProjectSnapshot,
    LaunchContextState,
    LaunchDefaultSnapshot,
)
from sase.current_project import CurrentProject
from sase.llm_provider.temporary_override import TemporaryLLMOverride


def _snapshot(
    *,
    provider: str = "codex",
    model: str = "o3",
    effort: str | None = "high",
    directive_label: str | None = "o3",
) -> LaunchDefaultSnapshot:
    return LaunchDefaultSnapshot(
        provider=provider,
        model=model,
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort=effort,
        directive_label=directive_label,
        palette=provider_text_palette(provider),
    )


def _project() -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def _project_snapshot() -> CurrentProjectSnapshot:
    project = _project()
    return CurrentProjectSnapshot(
        project=project,
        accent=project_accent(project.project_key, among=(project.project_key,)),
    )


def _override() -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="claude/opus",
        created_at=100.0,
        expires_at=3_820.0,
        source="test",
        effort="high",
    )


def _state(
    *,
    snapshot: LaunchDefaultSnapshot | None = None,
    override: TemporaryLLMOverride | None = None,
    project: CurrentProjectSnapshot | None = None,
    with_project: bool = True,
) -> LaunchContextState:
    if snapshot is None and override is None:
        snapshot = _snapshot()
    if project is None and with_project and snapshot is not None and override is None:
        project = _project_snapshot()
    return LaunchContextState(
        default_snapshot=snapshot,
        project_snapshot=project,
        override=override,
    )


def test_density_prefers_full_when_it_fits() -> None:
    assert choose_launch_context_density(28, full_cells=28, compact_cells=15) == "full"


def test_density_falls_back_to_compact_when_full_does_not_fit() -> None:
    assert (
        choose_launch_context_density(27, full_cells=28, compact_cells=15) == "compact"
    )
    assert (
        choose_launch_context_density(15, full_cells=28, compact_cells=15) == "compact"
    )


def test_density_renders_compact_when_nothing_fits() -> None:
    """Even compact renders on overflow; the host clips its own content."""

    assert choose_launch_context_density(0, full_cells=28, compact_cells=15) == (
        "compact"
    )
    assert choose_launch_context_density(-4, full_cells=28, compact_cells=15) == (
        "compact"
    )


async def _mounted_bar(page: AcePage) -> LaunchContextBar:
    bar = LaunchContextBar()
    await page.app.mount(bar)
    await page.pause()
    return bar


def _bar_plain(bar: LaunchContextBar) -> str:
    return "".join(
        child.render().plain
        for child in bar.children
        if getattr(child, "display", True)
    )


async def test_full_cluster_reads_label_chip_separator_label_chip() -> None:
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        bar.apply_launch_context(_state())
        await page.pause()

        assert bar.density == "full"
        assert _bar_plain(bar) == "MODEL: o3@high · PROJECT: +sase"


async def test_compact_cluster_hides_both_labels() -> None:
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        bar.apply_launch_context(_state())
        assert bar.set_density("compact") is True
        assert bar.set_density("compact") is False
        await page.pause()

        assert _bar_plain(bar) == "o3@high · +sase"


async def test_empty_project_collapses_group_without_dangling_separator() -> None:
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        bar.apply_launch_context(_state(project=CurrentProjectSnapshot(None, "")))
        await page.pause()

        separator = bar.query_one("#launch-separator", Static)
        project_label = bar.query_one("#launch-project-label", Static)
        assert separator.display is False
        assert project_label.display is False
        assert _bar_plain(bar) == "MODEL: o3@high"
        assert bar.full_cells == bar.compact_cells + len("MODEL: ")


async def test_override_switches_model_label_and_marks_gold_lane() -> None:
    until_cleared = TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="claude/opus",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort="high",
    )
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        bar.apply_launch_context(_state(snapshot=None, override=until_cleared))
        await page.pause()

        model_label = bar.query_one("#launch-model-label", Static)
        assert model_label.render().plain == "override "
        assert model_label.has_class("-override")
        assert model_label.tooltip == (
            "A temporary override is replacing the launch default."
        )
        model_view = bar.query_one(LLMOverrideIndicator)
        assert model_view.render().plain == "CLAUDE(opus)@high ∞"


async def test_calm_model_label_carries_default_tooltip() -> None:
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        bar.apply_launch_context(_state())
        await page.pause()

        model_label = bar.query_one("#launch-model-label", Static)
        assert model_label.render().plain == "MODEL: "
        assert not model_label.has_class("-override")
        assert model_label.tooltip == ("The model new agents launch with by default.")
        project_label = bar.query_one("#launch-project-label", Static)
        assert project_label.tooltip == "The project you are currently working in."


async def test_bar_forwards_one_state_to_both_views_identically() -> None:
    async with AcePage() as page:
        bar = await _mounted_bar(page)
        state = _state()
        bar.apply_launch_context(state)
        await page.pause()

        model_view = bar.query_one(LLMOverrideIndicator)
        project_view = bar.query_one(CurrentProjectIndicator)
        assert model_view._cached_default == ("codex", "o3")
        assert model_view._override is None
        assert project_view._cached_snapshot is not None
        assert project_view._cached_snapshot.project is not None
        assert project_view._cached_snapshot.project.display_name == "sase"


async def test_row_fit_picks_density_from_free_cells() -> None:
    from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel
    from sase.ace.tui.widgets.launch_context_bar import AxeInfoRow

    async with AcePage(size=(120, 40)) as page:
        page.app.current_tab = "axe"
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        row = page.query_one_widget("#axe-info-row", AxeInfoRow)
        await page.wait_for(lambda _state: row.region.width > 0)
        panel = row.query_one("#axe-info-panel", AxeInfoPanel)
        bar = row.query_one(LaunchContextBar)
        assert row.region.width > 0

        panel._content_width = 10
        row.fit_launch_context_bar()
        assert bar.density == "full"

        panel._content_width = row.region.width
        row.fit_launch_context_bar()
        assert bar.density == "compact"


def test_model_tooltip_calm_names_directives_and_config_surface() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = _snapshot(
        provider="claude", model="opus", effort="high", directive_label="opus"
    )

    assert indicator._build_tooltip(None) == (
        "Launch default: CLAUDE(opus) @ high\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )


def test_model_tooltip_round_robin_keeps_bare_is_next_label() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias="large",
        selector_mode="round_robin",
        member_count=3,
        effort="high",
        directive_label="opus",
        palette=provider_text_palette("claude"),
    )

    assert indicator._build_tooltip(None) == (
        "Launch default: CLAUDE(opus) @ high\n"
        "@large rotates across 3 models; CLAUDE(opus) is next.\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )


def test_model_tooltip_override_states() -> None:
    indicator = LLMOverrideIndicator()

    assert indicator._build_tooltip(_override(), now=100.0) == (
        "Temporary override: CLAUDE(opus) @ high · 1h2m left\n"
        "New agents use this instead of the launch default until it lapses.\n"
        "Click (or ,m) to change or clear it in Config › Launch."
    )

    until_cleared = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort=None,
    )
    assert indicator._build_tooltip(until_cleared, now=100.0) == (
        "Temporary override: CODEX(o3) · until cleared\n"
        "New agents use this instead of the launch default until it lapses.\n"
        "Click (or ,m) to change or clear it in Config › Launch."
    )


def test_model_tooltip_unresolved_and_failed_states() -> None:
    indicator = LLMOverrideIndicator()

    assert indicator._build_tooltip(None) == (
        "Launch default: resolving…\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )

    indicator._cached_default_failed = True
    assert indicator._build_tooltip(None).splitlines()[0] == (
        "Launch default: unavailable"
    )


@pytest.mark.parametrize(
    ("origin", "origin_ref", "workflow_type", "expected"),
    [
        ("project", "sase", "gh", "Set by your last launch (#gh:sase)"),
        ("patch", "my_patch", "gh", "Set via Patch my_patch"),
    ],
)
def test_project_tooltip_names_origin(
    origin: str, origin_ref: str, workflow_type: str, expected: str
) -> None:
    project = CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin=origin,  # type: ignore[arg-type]
        origin_ref=origin_ref,
        workflow_type=workflow_type,
    )

    assert CurrentProjectIndicator._build_tooltip(project, indicator=True) == (
        "Current project: sase\n"
        "Your working project: it seeds project filters and is "
        "preselected in the + launch picker.\n"
        f"{expected}\n"
        "Click to launch an agent on a project · "
        "press c on the Projects tab to switch."
    )
