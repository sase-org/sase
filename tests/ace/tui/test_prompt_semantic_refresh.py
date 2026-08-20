"""Agents-detail refresh after glossary/repo catalog publication."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext


class _CatalogApp(StartupPromptCatalogMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self._hint_mode_active = True
        self.refresh_calls: list[dict[str, Any]] = []
        self._prompt_glossary_generation = 1
        self._prompt_glossary_catalogs_by_context = {}
        self._prompt_glossary_diagnostics_by_context = {}
        self._prompt_glossary_warming_contexts = set()
        self._prompt_repo_mention_generation = 1
        self._prompt_repo_mention_catalogs_by_context = {}
        self._prompt_repo_mention_diagnostics_by_context = {}
        self._prompt_repo_mention_warming_contexts = set()

    def query(self, _widget_type: object) -> list[object]:
        return []

    def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
        self.refresh_calls.append({"render_immediate": render_immediate})


def test_glossary_and_repo_publication_coalesce_on_detail_debouncer_path() -> None:
    app = _CatalogApp()
    context = PromptGlossaryContext(project_ref="sase", launch_workspace=None)
    repo_context = PromptRepoMentionContext(project_ref="sase", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None
    app._prompt_repo_mention_catalogs_by_context[repo_context] = None

    app._refresh_visible_prompt_glossary_surfaces()
    app._refresh_visible_prompt_repo_mention_surfaces()

    assert app.refresh_calls == [
        {"render_immediate": False},
        {"render_immediate": False},
    ]


def test_invalidation_and_theme_change_reuse_the_same_detail_route() -> None:
    app = _CatalogApp()
    app._invalidate_prompt_glossary_catalogs(reason="config")
    app._invalidate_prompt_repo_mention_catalogs(reason="config")
    assert app.refresh_calls == [
        {"render_immediate": False},
        {"render_immediate": False},
    ]

    detail = SimpleNamespace(current_tab="agents", calls=[])

    def _refresh(*, render_immediate: bool = True) -> None:
        detail.calls.append(render_immediate)

    detail._refresh_agent_focus_detail = _refresh
    from sase.ace.tui.actions.agents._display_detail_render import (
        AgentDetailRenderMixin,
    )

    AgentDetailRenderMixin.watch_theme(detail, "textual-dark", "textual-light")
    assert detail.calls == [False]


def test_non_agents_tab_does_not_schedule_detail_refresh() -> None:
    app = _CatalogApp()
    app.current_tab = "artifacts"
    app._refresh_visible_prompt_semantic_surfaces()
    assert app.refresh_calls == []


def test_refresh_agent_focus_detail_is_noop_before_debouncer_exists() -> None:
    """Theme init on AceApp runs before ``_agent_detail_debouncer`` is installed."""
    from sase.ace.tui.actions.agents._display_detail_render import (
        AgentDetailRenderMixin,
    )

    class _Harness(AgentDetailRenderMixin):
        current_tab = "agents"

    harness = _Harness()
    harness.watch_theme(None, "sase-ace")
    harness._refresh_agent_focus_detail(render_immediate=False)
    harness._refresh_agent_focus_detail(render_immediate=True)
