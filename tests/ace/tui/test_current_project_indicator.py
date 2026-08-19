"""Tests for the ACE top-bar current-project chip."""

from __future__ import annotations

from typing import Literal

import pytest
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import current_project_indicator as indicator_module
from sase.ace.tui.widgets.current_project_indicator import (
    CurrentProjectIndicator,
    _CurrentProjectSnapshot,
)
from sase.current_project import CurrentProject


class _FakeWorker:
    """Duck-typed stand-in for ``textual.worker.Worker`` in unit tests."""

    def __init__(self, group: str, result: object) -> None:
        self.group = group
        self.result = result


class _FakeStateChanged:
    """Duck-typed stand-in for ``Worker.StateChanged`` in unit tests."""

    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


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


def _prepare_indicator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token: tuple[object, ...] = ("token-0",),
    settings: CurrentProjectSettings | None = None,
) -> tuple[CurrentProjectIndicator, list[object], list[object], list[object]]:
    """Build an unmounted indicator with worker spawning stubbed out."""

    peek_calls: list[object] = []
    resolve_calls: list[object] = []

    def peek() -> tuple[object, ...]:
        peek_calls.append(token)
        return token

    def resolve(**_kwargs: object) -> CurrentProject | None:
        resolve_calls.append(1)
        raise AssertionError("resolve_current_project must not run on the UI thread")

    monkeypatch.setattr(indicator_module, "peek_current_project_change_token", peek)
    monkeypatch.setattr(indicator_module, "resolve_current_project", resolve)
    indicator = CurrentProjectIndicator()
    scheduled: list[object] = []
    monkeypatch.setattr(
        indicator, "run_worker", lambda task, **kwargs: scheduled.append(task)
    )
    monkeypatch.setattr(indicator, "update", lambda *a, **k: None)
    if settings is not None:
        monkeypatch.setattr(indicator, "_settings", lambda: settings)
    return indicator, scheduled, peek_calls, resolve_calls


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


def test_refresh_peeks_but_does_not_resolve_when_token_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled, peek_calls, resolve_calls = _prepare_indicator(
        monkeypatch, token=("token-a",)
    )
    indicator._cached_token = ("token-a",)
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=_project(), accent="#fff"
    )

    indicator.refresh()

    assert peek_calls
    assert scheduled == []
    assert resolve_calls == []


def test_token_change_schedules_one_worker_and_second_tick_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled, _peek_calls, resolve_calls = _prepare_indicator(
        monkeypatch, token=("token-b",)
    )
    indicator._cached_token = ("token-a",)
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=_project(), accent="#fff"
    )

    indicator.refresh()
    indicator.refresh()

    assert len(scheduled) == 1
    assert resolve_calls == []


def test_refresh_never_calls_resolver_synchronously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled, _peek_calls, resolve_calls = _prepare_indicator(
        monkeypatch, token=("token-b",)
    )
    indicator._cached_token = ("token-a",)

    indicator.refresh()

    assert len(scheduled) == 1
    assert resolve_calls == []


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
        indicator_module, "resolve_current_project", lambda **_kwargs: None
    )

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#current-project-indicator", CurrentProjectIndicator
        )
        indicator._cached_snapshot = _CurrentProjectSnapshot(project=None, accent="")
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
        indicator._cached_snapshot = _CurrentProjectSnapshot(
            project=project,
            accent=project_accent(project.project_key, among=(project.project_key,)),
        )
        indicator._apply_content()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert indicator.render().plain == ""
        assert indicator.region.width == 0


def test_worker_success_commits_pending_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, _scheduled, _peek_calls, _resolve_calls = _prepare_indicator(monkeypatch)
    indicator._pending_resolve_token = ("pending-token",)
    indicator._resolve_in_flight = True
    snapshot = _CurrentProjectSnapshot(project=_project(), accent="#abc")

    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._WORKER_GROUP, snapshot),
            WorkerState.SUCCESS,
        )
    )

    assert indicator._cached_snapshot == snapshot
    assert indicator._cached_token == ("pending-token",)
    assert indicator._resolve_in_flight is False
    assert indicator._cached_failed is False


def test_invalidate_forces_resolve_when_refresh_would_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled, _peek_calls, resolve_calls = _prepare_indicator(
        monkeypatch, token=("token-a",)
    )
    indicator._cached_token = ("token-a",)
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=_project(), accent="#fff"
    )

    indicator.refresh()
    assert scheduled == []

    indicator.invalidate()

    assert len(scheduled) == 1
    assert resolve_calls == []
    assert indicator._cached_token is None
    assert indicator._resolve_in_flight is True

    indicator.refresh()
    assert len(scheduled) == 1


def test_invalidate_is_noop_while_resolve_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled, _peek_calls, resolve_calls = _prepare_indicator(
        monkeypatch, token=("token-b",)
    )
    indicator._cached_token = ("token-a",)
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=_project(), accent="#fff"
    )
    indicator._resolve_in_flight = True

    indicator.invalidate()

    assert scheduled == []
    assert resolve_calls == []
    assert indicator._cached_token == ("token-a",)
    assert indicator._resolve_in_flight is True
