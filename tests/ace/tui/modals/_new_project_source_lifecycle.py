"""Provider lifecycle tests for the New Project source stage."""

from __future__ import annotations

import asyncio

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.project_onboarding import CandidateInputs, Preferences
from tests.ace.tui.modals._new_project_source_helpers import (
    ModalApp,
    inputs,
    provider,
    tool_missing_inputs,
)


async def test_tool_missing_disables_provider_tab(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(
            provider("gh", "GitHub"),
            provider("git", "Git (bare)"),
        ),
        candidate_inputs={
            "gh": tool_missing_inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip

        strip_widget = modal.query_one(PanelTabStrip)
        assert strip_widget.is_tab_disabled("gh")
        assert not strip_widget.is_tab_disabled("git")
        # The wizard steps off the disabled tab onto the working provider.
        assert modal._state.workflow_type == "git"
        assert modal._state.stage == "source"
        modal.select_provider("gh")
        assert modal._state.workflow_type == "git"


async def test_unmount_cancels_owner_refresh_jobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import threading

    import sase.ace.tui.modals.new_project_modal_providers as _providers

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    release = threading.Event()

    def _slow_load(workflow_type, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("cache_only"):
            return inputs()
        assert release.wait(timeout=15), "live owner refresh must be released"
        return inputs()

    monkeypatch.setattr(_providers, "load_candidate_inputs", _slow_load)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    wizard_queries: list[str] = []
    _real_query_one = modal.query_one

    def _recording_query_one(*args, **kwargs):  # type: ignore[no-untyped-def]
        wizard_queries.append(str(args[0]) if args else "")
        return _real_query_one(*args, **kwargs)

    monkeypatch.setattr(modal, "query_one", _recording_query_one)
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal._loaded.discard("gh")
        modal._start_provider_load("gh")
        await wait_for(pilot, lambda: len(modal._owner_jobs) > 0)
        parents = {
            task
            for task in asyncio.all_tasks()
            if str(task.get_name()).startswith("new-project-load:gh")
        }
        assert parents, "the real provider load must be in flight"
        children = set(modal._owner_jobs)
        assert children, "real owner refresh jobs must be in flight"
        wizard_queries.clear()
        app.pop_screen()
        # Let teardown land while the owner threads are still blocked: the
        # parent must end cancelled (propagation, not a swallowed break).
        await wait_for(pilot, lambda: all(task.done() for task in parents | children))
        for task in parents:
            assert task.cancelled(), "cancelled refresh must propagate, not swallow"
        for task in children:
            assert task.cancelled(), "teardown must cancel owner jobs"
        release.set()
        await pilot.pause()
        assert modal._loading == set()
        assert modal._refresh_queued == set()
        assert modal._teardown_started
        touched = [
            selector
            for selector in wizard_queries
            if selector.startswith("#new-project-") or "NewProjectSource" in selector
        ]
        assert touched == [], f"teardown touched the DOM: {touched}"


async def test_disabled_tab_fallback_does_not_persist_provider(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import json

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    prefs_dir = tmp_path / "project_onboarding"
    prefs_dir.mkdir(parents=True)
    (prefs_dir / "preferences.json").write_text(
        json.dumps({"last_provider": "gh", "last_owner": {"gh": "sase-org"}})
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(
            provider("gh", "GitHub"),
            provider("git", "Git (bare)"),
        ),
        candidate_inputs={
            "gh": tool_missing_inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        # Automatic fallback steps off the broken provider...
        assert modal._state.workflow_type == "git"
        # ...without persisting it over the user's saved provider.
        await pilot.pause(0.2)
        assert modal._preferences.last_provider == "gh"
        payload = json.loads((prefs_dir / "preferences.json").read_text())
        assert payload["last_provider"] == "gh"


async def test_post_remedy_refresh_queues_behind_load(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        assert modal._state.workflow_type == "gh"
        modal._loading.add("gh")
        modal.action_refresh_provider()
        assert modal._refresh_queued == {"gh"}
        refreshes: list[str] = []

        async def _fake_refresh(workflow_type: str, *, force: bool) -> None:
            refreshes.append(workflow_type)
            modal._loading.discard(workflow_type)

        monkeypatch.setattr(modal, "_refresh_all_owners", _fake_refresh)
        modal._finish_provider_load("gh")
        await pilot.pause()
        assert refreshes == ["gh"]
        assert modal._refresh_queued == set()
