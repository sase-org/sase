"""Current-project seeding precedence for the Memory panel's initial load."""

from __future__ import annotations

import pytest

from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeRef,
    MemoryScopeSnapshot,
)
from sase.ace.tui.modals import memory_panel_load as mpl
from sase.current_project import CurrentProject


def _scope(key: str, display_name: str) -> MemoryScopeRef:
    return MemoryScopeRef(
        kind="project",
        key=key,
        display_name=display_name,
        content_root="",
        memory_read_root=None,
        has_memory=True,
    )


def _snapshot(ref: MemoryScopeRef) -> MemoryScopeSnapshot:
    return MemoryScopeSnapshot(
        scope=ref,
        notes=(),
        tree=(),
        digests={},
        stats={},
        shadowed_stems=frozenset(),
        generated_paths=frozenset(),
        read_summaries={},
        diagnostics=(),
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ring: tuple[MemoryScopeRef, ...] = (),
    current_project: CurrentProject | None,
) -> None:
    monkeypatch.setattr(mpl, "build_memory_scope_ring", lambda _workspace: ring)
    monkeypatch.setattr(mpl, "load_memory_scope_snapshot", _snapshot)

    def fake_resolve(**_kwargs: object) -> CurrentProject | None:
        return current_project

    monkeypatch.setattr(mpl, "resolve_current_project", fake_resolve)


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
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None, initial_scope_key=None
    )

    assert result.scope_index == 1


def test_initial_scope_key_wins_over_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None, initial_scope_key="alpha"
    )

    assert result.scope_index == 0


def test_session_scope_key_wins_over_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None,
        session_scope_key="alpha",
    )

    assert result.scope_index == 0


def test_initial_scope_key_wins_over_session_scope_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None,
        initial_scope_key="alpha",
        session_scope_key="beta",
    )

    assert result.scope_index == 0


def test_vanished_initial_scope_key_falls_back_to_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=None)

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None,
        initial_scope_key="gone",
        session_scope_key="beta",
    )

    assert result.scope_index == 1


def test_seed_disabled_flag_keeps_default_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("beta"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None,
        initial_scope_key=None,
        seed_from_current_project=False,
    )

    assert result.scope_index == 0


def test_current_project_not_in_ring_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    _install(monkeypatch, ring=ring, current_project=_current("gamma"))

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None, initial_scope_key=None
    )

    assert result.scope_index == 0


def test_current_project_resolve_failure_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = (_scope("alpha", "Alpha"), _scope("beta", "Beta"))
    monkeypatch.setattr(mpl, "build_memory_scope_ring", lambda _workspace: ring)
    monkeypatch.setattr(mpl, "load_memory_scope_snapshot", _snapshot)

    def raising_resolve(**_kwargs: object) -> CurrentProject | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(mpl, "resolve_current_project", raising_resolve)

    result = mpl.load_memory_panel_initial_state(
        launch_workspace=None, initial_scope_key=None
    )

    assert result.scope_index == 0


def test_empty_ring_returns_no_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, ring=(), current_project=_current("alpha"))

    result = mpl.load_memory_panel_initial_state(launch_workspace=None)

    assert result.ring == ()
    assert result.scope_index == 0
    assert result.snapshot is None
