"""Tests for the ACE top-bar current-project chip."""

from __future__ import annotations

from typing import Literal

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import launch_context_source as source_module
from sase.ace.tui.widgets.current_project_indicator import CurrentProjectIndicator
from sase.ace.tui.widgets.launch_context_source import CurrentProjectSnapshot
from sase.current_project import CurrentProject


def _project(
    *,
    origin: Literal["project", "patch"] = "project",
    origin_ref: str = "sase",
    display_name: str = "sase",
) -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name=display_name,
        origin=origin,
        origin_ref=origin_ref,
        workflow_type="gh",
    )


def test_resolved_project_renders_display_name_with_accent() -> None:
    project = _project()
    enabled = (project.project_key, "other")
    accent = project_accent(project.project_key, among=enabled)

    text = CurrentProjectIndicator._build_content(
        project, accent=accent, indicator=True
    )

    assert text.plain == " +sase "
    styled = [
        (text.plain[span.start : span.end], str(span.style)) for span in text.spans
    ]
    assert (" +", f"dim {accent}") in styled
    assert ("sase", f"bold {accent}") in styled


def test_unresolved_and_disabled_render_empty() -> None:
    project = _project()
    accent = project_accent(project.project_key, among=(project.project_key,))

    unresolved = CurrentProjectIndicator._build_content(
        None, accent=accent, indicator=True
    )
    disabled = CurrentProjectIndicator._build_content(
        project, accent=accent, indicator=False
    )

    assert unresolved.plain == ""
    assert disabled.plain == ""
    assert CurrentProjectIndicator._build_tooltip(None, indicator=True) is None
    assert CurrentProjectIndicator._build_tooltip(project, indicator=False) is None


def test_patch_origin_renders_project_name_and_names_patch_in_tooltip() -> None:
    project = _project(origin="patch", origin_ref="my_patch")
    accent = project_accent(project.project_key, among=(project.project_key,))

    text = CurrentProjectIndicator._build_content(
        project, accent=accent, indicator=True
    )
    tooltip = CurrentProjectIndicator._build_tooltip(project, indicator=True)

    assert text.plain == " +sase "
    assert "my_patch" not in text.plain
    assert tooltip == (
        "sase\n"
        "via Patch my_patch\n"
        "#gh:my_patch\n"
        "Launch an agent on a project, or press c on the Projects tab, "
        "to make it current."
    )


def test_project_origin_tooltip_names_mru_ref_and_launch_hint() -> None:
    project = _project()

    tooltip = CurrentProjectIndicator._build_tooltip(project, indicator=True)

    assert tooltip == (
        "sase\n#gh:sase\nLaunch an agent on a project, or press c on the "
        "Projects tab, to make it current."
    )


async def test_click_dispatches_start_custom_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def capture(action: str, *args: object, **kwargs: object) -> None:
        calls.append(action)

    async with AcePage() as page:
        monkeypatch.setattr(page.app, "run_action", capture)
        indicator = page.query_one_widget(
            "#current-project-indicator", CurrentProjectIndicator
        )
        await indicator.on_click()
        await page.pause()

    assert calls == ["start_custom_agent"]


async def test_unresolved_chip_takes_zero_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source_module, "resolve_current_project", lambda **_kwargs: None
    )

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#current-project-indicator", CurrentProjectIndicator
        )
        indicator._cached_snapshot = CurrentProjectSnapshot(project=None, accent="")
        indicator._apply_content()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert indicator.render().plain == ""
        assert indicator.region.width == 0


async def test_disabled_indicator_takes_zero_width_when_resolved() -> None:
    project = _project()

    async with AcePage() as page:
        page.app._current_project_settings = CurrentProjectSettings(indicator=False)
        indicator = page.query_one_widget(
            "#current-project-indicator", CurrentProjectIndicator
        )
        indicator._cached_snapshot = CurrentProjectSnapshot(
            project=project,
            accent=project_accent(project.project_key, among=(project.project_key,)),
        )
        indicator._apply_content()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert indicator.render().plain == ""
        assert indicator.region.width == 0
