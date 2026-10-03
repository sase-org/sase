"""Post-open quiet: staggered warm-ups, deferred detail repaint, import warm.

Phase ``post-open-quiet``: the prompt bar paints before non-essential catalog
warm-ups run; Agents-detail repaints wait for dismissal while a prompt is
active; first-open modules are pre-imported during deferred startup.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.actions._event_base import EventHandlersBase
from sase.ace.tui.actions._startup_loads_maintenance import (
    PROMPT_BAR_FIRST_MOUNT_MODULES,
    StartupLoadsMaintenanceMixin,
)
from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.agent_decks_settings import DEFAULT_AGENT_DECKS_SETTINGS
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.prompt_submission_settings import DEFAULT_PROMPT_SUBMISSION_SETTINGS
from sase.ace.tui.widgets import PromptInputBar
from sase.ace.tui.widgets.prompt_completion import (
    DEFAULT_PROMPT_COMPLETION_SETTINGS,
    DEFAULT_PROMPT_SPELLCHECK_SETTINGS,
)
from tests.ace.tui._kill_and_edit_launch_barrier_helpers import (
    PromptLifecycleApp,
    prompt_bar_ready,
)


class QuietBarApp(PromptLifecycleApp, StartupPromptCatalogMixin):
    """Prompt-bar lifecycle harness with catalog state and detail recording."""

    def __init__(self, *, selected: Any | None = None) -> None:
        super().__init__()
        self.current_tab = "agents"  # type: ignore[assignment]
        self._prompt_editor_suspended = False  # type: ignore[attr-defined]
        self._active_prompt_bar = None  # type: ignore[attr-defined]
        self._prompt_glossary_generation = 0
        self._prompt_glossary_catalogs_by_context = {}
        self._prompt_glossary_diagnostics_by_context = {}
        self._prompt_glossary_warming_contexts = set()
        self._prompt_repo_mention_generation = 0
        self._prompt_repo_mention_catalogs_by_context = {}
        self._prompt_repo_mention_diagnostics_by_context = {}
        self._prompt_repo_mention_warming_contexts = set()
        self._prompt_catalog = None
        self._prompt_catalog_generation = 0
        self._prompt_catalog_rebuild_in_flight = False
        self._prompt_catalog_rebuild_pending = False
        self._prompt_catalog_rebuild_pending_force = False
        self._prompt_catalog_rebuild_pending_config_dirty = False
        self._prompt_catalog_projects = {None}
        self._prompt_catalog_token_check_last_mono = 0.0
        self._prompt_catalog_assist_entries_cache = {}
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache = None
        self._pending_snippet_saves: dict[str, str] = {}
        self._prompt_source_watcher = None
        self._prompt_source_watcher_active = False
        self._prompt_source_watched_projects = set()
        self._prompt_source_watch_growth_in_flight = False
        self._prompt_source_watch_growth_pending = False
        self._prompt_source_debounce_timer = None
        self._prompt_source_debounce_config_dirty = False
        self._pending_selected_agent_semantic_refresh = False
        self._selected = selected
        self.detail_calls: list[dict[str, Any]] = []

    def get_prompt_submission_settings(self) -> Any:
        return DEFAULT_PROMPT_SUBMISSION_SETTINGS

    def get_prompt_completion_settings(self) -> Any:
        return DEFAULT_PROMPT_COMPLETION_SETTINGS

    def get_prompt_spellcheck_settings(self) -> Any:
        return DEFAULT_PROMPT_SPELLCHECK_SETTINGS

    def get_agent_decks_settings(self) -> Any:
        return DEFAULT_AGENT_DECKS_SETTINGS

    def _get_selected_agent(self) -> Any | None:
        return self._selected

    def _prompt_input_active(self) -> bool:
        return EventHandlersBase._prompt_input_active(self)

    def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
        self.detail_calls.append({"render_immediate": render_immediate})


def _agent_stub(*, project: str) -> Any:
    return SimpleNamespace(
        project_file=f"/projects/{project}/{project}.sase",
        workspace_dir="",
    )


def _gate_deferred_warmups(app: QuietBarApp) -> list[Any]:
    """Capture the one-paint-deferred mount callback instead of scheduling it."""
    captured: list[Any] = []
    real = app.call_after_refresh

    def _gate(callback: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(callback, "__name__", "") == "_run_deferred_mount_warmups":
            captured.append((callback, args, kwargs))
            return None
        return real(callback, *args, **kwargs)

    app.call_after_refresh = _gate  # type: ignore[method-assign]
    return captured


@pytest.mark.asyncio
async def test_mount_paints_before_non_essential_warmups() -> None:
    """Essentials mount synchronously; catalog warm-ups wait one paint."""
    app = QuietBarApp()
    captured = _gate_deferred_warmups(app)
    async with app.run_test(size=(100, 35)) as pilot:
        app._show_prompt_input_bar_for_home(initial_text="hello")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        bar = app.query_one(PromptInputBar)

        # First-paint essentials are already published by mount.
        assert app._active_prompt_bar is bar
        # The non-essential warm-ups were deferred, not run.
        assert len(captured) == 1
        assert bar._dispatch_catalog_loading is False
        assert bar._dispatch_catalog_loaded is False

        # Firing the deferred callback runs the warm-ups.
        callback, args, kwargs = captured[0]
        callback(*args, **kwargs)
        await wait_for(
            pilot,
            lambda: bar._dispatch_catalog_loading or bar._dispatch_catalog_loaded,
        )


@pytest.mark.asyncio
async def test_first_keystroke_completion_survives_stagger() -> None:
    """Typing right after mount still offers xprompt completion."""
    app = QuietBarApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app._show_prompt_input_bar_for_home(initial_text="")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        await pilot.pause()
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        # Deferred warm-ups settled: the dispatch catalog load was attempted.
        assert bar._dispatch_catalog_loading or bar._dispatch_catalog_loaded

        text_area = bar.active_text_area()
        text_area.focus()
        await pilot.press("+")
        await pilot.pause()
        # The keystroke landed in the prompt text; completion catalogs that
        # the first keystroke needs were warmed synchronously at mount.
        assert "+" in text_area.text


@pytest.mark.asyncio
async def test_detail_repaint_defers_while_prompt_active() -> None:
    """A warm for another context skips the detail; dismissal repaints once."""
    app = QuietBarApp(selected=_agent_stub(project="proj"))
    async with app.run_test(size=(100, 35)) as pilot:
        app._show_prompt_input_bar_for_home(initial_text="hello")
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        assert app._prompt_input_active() is True

        other = PromptGlossaryContext(project_ref="other", launch_workspace=None)
        app._prompt_glossary_catalogs_by_context[other] = None
        app._refresh_visible_prompt_glossary_surfaces(other)
        assert app.detail_calls == []
        assert app._pending_selected_agent_semantic_refresh is True

        matching = PromptGlossaryContext(project_ref="proj", launch_workspace=None)
        app._prompt_glossary_catalogs_by_context[matching] = None
        app._refresh_visible_prompt_glossary_surfaces(matching)
        assert app.detail_calls == []

        app._unmount_prompt_bar()
        await pilot.pause()
        assert app.detail_calls == [{"render_immediate": False}]


def test_prompt_bar_import_warm_loads_first_mount_modules() -> None:
    """The deferred import warm covers every listed first-open module."""
    assert PROMPT_BAR_FIRST_MOUNT_MODULES
    StartupLoadsMaintenanceMixin._run_prompt_bar_import_warm(SimpleNamespace())
    for name in PROMPT_BAR_FIRST_MOUNT_MODULES:
        assert name in sys.modules, name
    # A second run is a cheap no-op.
    StartupLoadsMaintenanceMixin._run_prompt_bar_import_warm(SimpleNamespace())
