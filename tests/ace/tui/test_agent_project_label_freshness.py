"""Project labels show PROJECT_NAME even for cross-process creation/renames."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from rich.text import Text

from sase import project_display_names as pdn
from sase.ace.tui.models._agent_clan import ClanStatusCounts, clan_project_labels
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from tests._project_display_case import ProjectDisplayCase

_GENERATION = "20261001120000"
_START = datetime(2026, 10, 1, 12, 0, 0)


def _reset_display_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_FRESHNESS_TOKENS", None)


def _member(
    case: ProjectDisplayCase,
    suffix: str,
    project_file: str,
    *,
    display: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=case.project_key,
        project_file=project_file,
        status="RUNNING",
        start_time=_START,
        run_start_time=_START,
        raw_suffix=suffix,
        agent_name=f"research.{suffix}",
        agent_clan="research",
        agent_clan_generation=_GENERATION,
        project_display_name=display,
    )


def _container(members: list[Agent]) -> Agent:
    containers = [
        row
        for row in project_clan_tree(members)
        if row.is_clan_container and row.agent_clan == "research"
    ]
    assert containers, "expected a clan container"
    return containers[0]


def _stale_startup_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: ProjectDisplayCase,
) -> tuple[Agent, Agent]:
    """Warm a stale cache, create the project out-of-process, reload as a worker."""
    _reset_display_cache(monkeypatch)
    root = tmp_path / "projects"
    root.mkdir()
    # Point the default projects dir at the fixture root so the no-arg worker
    # path below resolves exactly like the production TUI worker.
    monkeypatch.setattr(pdn, "sase_projects_dir", lambda: root)
    # Warm the convenience cache against a root that lacks the project.
    assert pdn.project_display_name_for(case.project_key) == case.project_key

    def _forbidden_invalidate(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no in-process hook may rescue cross-process creation")

    monkeypatch.setattr(
        pdn, "invalidate_project_display_snapshot", _forbidden_invalidate
    )
    layout = case.write_project_layout(root)

    from sase.ace.tui.actions.agents._loading_compute import (
        compute_apply_loaded_agents,
    )

    members = [
        _member(case, "one", str(layout.project_file)),
        _member(case, "two", str(layout.project_file)),
    ]
    prep = compute_apply_loaded_agents(members, [], set(), False)
    containers = [row for row in prep.filtered_agents if row.is_clan_container]
    assert containers, "expected the worker load to project a clan container"
    return containers[0], members[0]


def test_stale_startup_worker_load_shows_configured_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A TUI started before a project exists shows PROJECT_NAME after its load."""
    case = project_display_case
    container, member = _stale_startup_container(tmp_path, monkeypatch, case)

    assert member.project_display_name == case.project_label
    assert clan_project_labels(container) == (case.project_label,)

    from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option

    left, suffix, _ = format_agent_option(container, 0, is_selected=False)
    row_text = left.plain + suffix.plain
    assert case.project_label in row_text
    case.assert_no_key_leak(row_text)

    from sase.ace.tui.models.fold_state import FoldLevel
    from sase.ace.tui.widgets.prompt_panel._agent_display_clan_identity import (
        append_clan_identity_fields,
        build_clan_compact_lines,
    )

    full = Text()
    append_clan_identity_fields(
        full,
        container,
        counts=ClanStatusCounts(),
        agent_count=2,
        agent_session_count=0,
        fold_level=FoldLevel.COLLAPSED,
    )
    assert case.project_label in full.plain
    case.assert_no_key_leak(full.plain)

    compact = build_clan_compact_lines(
        agent=container,
        counts=ClanStatusCounts(),
        agent_count=2,
        agent_session_count=0,
        fold_level=FoldLevel.COLLAPSED,
    )
    assert case.project_label in compact.plain
    case.assert_no_key_leak(compact.plain)

    from sase.ace.tui.models.agent_groups._keys import grouping_keys_for_agents
    from sase.ace.tui.models.agent_groups._buckets import GroupingMode

    keys = grouping_keys_for_agents([member], mode=GroupingMode.STANDARD)
    assert keys[0].project == case.project_label
    case.assert_no_key_leak(keys[0].project)

    from sase.ace.tui.widgets.prompt_panel._identity_header_compact import (
        _fallback_context_line,
    )

    fallback = _fallback_context_line(member)
    assert case.project_label in fallback.plain
    case.assert_no_key_leak(fallback.plain)

    from sase.ace.tui.actions.agent_workflow._launch_submit_helpers import (
        launch_toast_label,
    )

    toast = launch_toast_label(f"#gh:{case.project_key} do work", case.project_key)
    assert toast == case.project_label
    case.assert_no_key_leak(toast)


def test_rename_by_another_process_propagates_on_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A PROJECT_NAME rewrite on disk flips labels on the next refresh."""
    case = project_display_case
    _reset_display_cache(monkeypatch)
    root = tmp_path / "projects"
    root.mkdir()
    layout = case.write_project_layout(root)

    assert pdn.refresh_project_display_snapshot(root) is True
    assert pdn.project_display_name_for(case.project_key, root) == case.project_label

    layout.project_file.write_text(
        f"PROJECT_NAME: gizmos\nWORKSPACE_DIR: {layout.workspace_dir}\n",
        encoding="utf-8",
    )
    gen_before = pdn._HUMANIZE_CACHE_GEN
    assert pdn.refresh_project_display_snapshot(root) is True
    assert pdn._HUMANIZE_CACHE_GEN != gen_before
    assert pdn.project_display_name_for(case.project_key, root) == "gizmos"
    assert pdn.humanize_cl_name(case.project_key, root) == "gizmos"

    member = _member(case, "one", str(layout.project_file))
    pdn.attach_project_display_names([member], root)
    assert member.project_display_name == "gizmos"
    container = _container([member])
    assert clan_project_labels(container) == ("gizmos",)
    case.assert_no_key_leak(clan_project_labels(container)[0])


def test_running_only_churn_never_clears_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A spec edit that only touches RUNNING keeps labels and memo generations."""
    case = project_display_case
    _reset_display_cache(monkeypatch)
    root = tmp_path / "projects"
    root.mkdir()
    layout = case.write_project_layout(root)

    assert pdn.refresh_project_display_snapshot(root) is True
    gen_before = pdn._HUMANIZE_CACHE_GEN
    assert pdn.humanize_cl_name(case.project_key, root) == case.project_label

    layout.project_file.write_text(
        layout.project_file.read_text(encoding="utf-8")
        + "\nRUNNING:\n  #1 | 123 | run | demo\n",
        encoding="utf-8",
    )
    assert pdn.refresh_project_display_snapshot(root) is False
    assert pdn._HUMANIZE_CACHE_GEN == gen_before
    assert pdn.project_display_name_for(case.project_key, root) == case.project_label


def test_unchanged_token_skips_inventory_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A quiet tick performs no lifecycle inventory read at all."""
    case = project_display_case
    _reset_display_cache(monkeypatch)
    root = tmp_path / "projects"
    root.mkdir()
    case.write_project_layout(root)

    assert pdn.refresh_project_display_snapshot(root) is True

    calls = 0
    real_list = pdn.list_project_records

    def _counting(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(pdn, "list_project_records", _counting)
    assert pdn.refresh_project_display_snapshot(root) is False
    assert calls == 0


def test_failed_inventory_read_keeps_labels_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A failed reload keeps the previous snapshot; the next call retries."""
    case = project_display_case
    _reset_display_cache(monkeypatch)
    root = tmp_path / "projects"
    root.mkdir()
    layout = case.write_project_layout(root)

    assert pdn.refresh_project_display_snapshot(root) is True
    assert pdn.project_display_name_for(case.project_key, root) == case.project_label

    layout.project_file.write_text(
        layout.project_file.read_text(encoding="utf-8") + "\n# churn\n",
        encoding="utf-8",
    )

    real_list = pdn.list_project_records

    def _fail(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(pdn, "list_project_records", _fail)
    assert pdn.refresh_project_display_snapshot(root) is False
    assert pdn.project_display_name_for(case.project_key, root) == case.project_label

    calls = 0

    def _counting(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(pdn, "list_project_records", _counting)
    # The failed attempt kept the old token, so the next call retries the load.
    assert pdn.refresh_project_display_snapshot(root) is False
    assert calls == 1
    assert pdn.project_display_name_for(case.project_key, root) == case.project_label


@pytest.mark.asyncio
async def test_auto_refresh_tick_marks_agents_dirty_on_label_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    """A tick that detects a label change reloads agents through the dirty flag."""
    del tmp_path, project_display_case
    from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

    from sase import project_display_names as pdn

    app = _FakeApp(watcher_active=True)
    assert app._dirty_agents is False

    # Warm the map like the startup load does, then simulate a label change
    # detected on the tick.
    pdn.refresh_project_display_snapshot()
    monkeypatch.setattr(pdn, "refresh_project_display_snapshot", lambda *a, **k: True)
    await app._run_auto_refresh()

    # The detected change marked the agents surface dirty, so the existing
    # refresh path consumed it with a broad agents load.
    assert "agents" in app.refresh_calls
