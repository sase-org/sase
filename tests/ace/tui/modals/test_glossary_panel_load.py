"""Current-project seeding precedence for the Glossary panel's initial load."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import glossary_panel_load as gpl
from sase.current_project import CurrentProject

from .glossary_panel_test_helpers import project_ref, project_snapshot


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ring: tuple = (),
    current_project: CurrentProject | None,
) -> None:
    monkeypatch.setattr(gpl, "build_glossary_project_ring", lambda _workspace: ring)
    monkeypatch.setattr(
        gpl,
        "load_glossary_project_snapshot",
        lambda ref: project_snapshot(ref),
    )

    def fake_resolve(**_kwargs: object) -> CurrentProject | None:
        return current_project

    monkeypatch.setattr(gpl, "resolve_current_project", fake_resolve)


def _current(project_key: str) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=project_key,
        origin="project",
        origin_ref=project_key,
        workflow_type="gh",
    )


def test_seeds_from_current_project_when_no_initial_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None, initial_project_key=None
    )

    assert result.project_index == 1


def test_initial_project_key_wins_over_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None, initial_project_key="alpha"
    )

    assert result.project_index == 0


def test_seed_disabled_flag_keeps_default_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None,
        initial_project_key=None,
        seed_from_current_project=False,
    )

    assert result.project_index == 0


def test_current_project_not_in_ring_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("gamma"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None, initial_project_key=None
    )

    assert result.project_index == 0


def test_current_project_resolve_failure_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    monkeypatch.setattr(gpl, "build_glossary_project_ring", lambda _workspace: ring)
    monkeypatch.setattr(
        gpl,
        "load_glossary_project_snapshot",
        lambda ref: project_snapshot(ref),
    )

    def raising_resolve(**_kwargs: object) -> CurrentProject | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(gpl, "resolve_current_project", raising_resolve)

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None, initial_project_key=None
    )

    assert result.project_index == 0


def test_session_project_key_used_when_no_initial_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("alpha"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None,
        initial_project_key=None,
        seed_from_current_project=False,
        session_project_key="beta",
    )

    assert result.project_index == 1


def test_initial_project_key_wins_over_session_project_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (project_ref("alpha", "Alpha"), project_ref("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = gpl.load_glossary_panel_initial_state(
        launch_workspace=None,
        initial_project_key="alpha",
        session_project_key="beta",
    )

    assert result.project_index == 0
