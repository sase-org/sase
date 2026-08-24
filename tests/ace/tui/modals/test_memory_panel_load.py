"""Current-project seeding precedence for the Memory panel's initial load."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeRef,
    MemoryScopeSnapshot,
)
from sase.ace.tui.modals import memory_panel_load as mpl
from sase.current_project import CurrentProject
from sase.feature_flags import override_flags
from sase.memory.read_log import memory_read_log_path, read_memory_read_events


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


def test_record_strand_read_uses_memory_read_audit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "sase" / "memory"
    memory_root.mkdir(parents=True)
    (memory_root / "decisions.md").write_text(
        "---\ntype: core\nweb: true\n---\nDescriptor.\n",
        encoding="utf-8",
    )
    strand_dir = memory_root / "decisions"
    strand_dir.mkdir()
    (strand_dir / "alpha.md").write_text(
        "---\nkeyword: Alpha\nsummary: Alpha summary.\n---\nAlpha body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    monkeypatch.chdir(tmp_path)
    scope = MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(tmp_path),
        memory_read_root=str(memory_root),
        has_memory=True,
    )

    with override_flags(memory_webs=True):
        result = mpl.record_memory_panel_strand_read(
            scope,
            web_slug="decisions",
            strand_slug="alpha",
        )

    assert result.identity == "decisions:alpha"
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].kind == "strand"
    assert events[0].selectors == ("decisions:alpha",)
    assert events[0].resolved_targets == ("decisions:alpha",)
    assert events[0].included_targets == ()
    assert events[0].agent_name == "agent-a"
