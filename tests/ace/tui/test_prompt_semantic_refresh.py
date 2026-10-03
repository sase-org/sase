"""Agents-detail refresh after glossary/repo catalog publication."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext


class _CatalogApp(StartupPromptCatalogMixin):
    def __init__(
        self,
        *,
        selected: Any | None = None,
        prompt_active: bool = False,
        areas: list[object] | None = None,
    ) -> None:
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
        self._pending_selected_agent_semantic_refresh = False
        self._selected = selected
        self._prompt_active = prompt_active
        self._areas = list(areas) if areas is not None else []

    def query(self, _widget_type: object) -> list[object]:
        return self._areas

    def _get_selected_agent(self) -> Any | None:
        return self._selected

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
        self.refresh_calls.append({"render_immediate": render_immediate})


class _LegacyCatalogApp(StartupPromptCatalogMixin):
    """Host without a selected-agent accessor: legacy always-repaint."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.refresh_calls: list[dict[str, Any]] = []
        self._pending_selected_agent_semantic_refresh = False

    def query(self, _widget_type: object) -> list[object]:
        return []

    def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
        self.refresh_calls.append({"render_immediate": render_immediate})


def _agent_stub(*, project: str | None, workspace: str | None = None) -> Any:
    project_file = f"/projects/{project}/{project}.sase" if project else ""
    return SimpleNamespace(project_file=project_file, workspace_dir=workspace or "")


def _area_stub(*, display: bool = True, visible: bool = True) -> Any:
    calls: list[str] = []
    area = SimpleNamespace(is_mounted=True, calls=calls)
    area.display = display
    area.visible = visible
    area._build_highlight_map = lambda: calls.append("highlight")
    area.refresh = lambda *args, **kwargs: calls.append("refresh")
    return area


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


def test_matching_context_warm_repaints_when_idle() -> None:
    """A warm for the selected agent's context repaints the detail."""
    app = _CatalogApp(selected=_agent_stub(project="proj"))
    context = PromptGlossaryContext(project_ref="proj", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None

    app._refresh_visible_prompt_glossary_surfaces(context)

    assert app.refresh_calls == [{"render_immediate": False}]


def test_mismatched_context_warm_skips_detail_repaint() -> None:
    """A warm for another context never touches the selected detail."""
    app = _CatalogApp(selected=_agent_stub(project="proj"))
    context = PromptGlossaryContext(project_ref="other", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None

    app._refresh_visible_prompt_glossary_surfaces(context)

    assert app.refresh_calls == []


def test_workspace_mismatch_skips_detail_repaint() -> None:
    """Same project but a different workspace still skips the repaint."""
    app = _CatalogApp(selected=_agent_stub(project="proj", workspace="/ws/1"))
    context = PromptRepoMentionContext(project_ref="proj", launch_workspace="/ws/2")
    app._prompt_repo_mention_catalogs_by_context[context] = None

    app._refresh_visible_prompt_repo_mention_surfaces(context)

    assert app.refresh_calls == []


def test_empty_selection_skips_context_scoped_repaint() -> None:
    """With no agent selected, a context warm cannot affect the detail."""
    app = _CatalogApp(selected=None)
    context = PromptGlossaryContext(project_ref="proj", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None

    app._refresh_visible_prompt_glossary_surfaces(context)

    assert app.refresh_calls == []


def test_legacy_host_without_selected_accessor_repaints() -> None:
    """Hosts without ``_get_selected_agent`` keep always-repaint behavior."""
    app = _LegacyCatalogApp()
    context = PromptGlossaryContext(project_ref="proj", launch_workspace=None)

    app._refresh_visible_prompt_semantic_surfaces(context)

    assert app.refresh_calls == [{"render_immediate": False}]


def test_prompt_active_defers_repaint_and_flush_coalesces_once() -> None:
    """Warms during a prompt set the pending flag; dismissal flushes once."""
    app = _CatalogApp(
        selected=_agent_stub(project="proj"),
        prompt_active=True,
    )
    matching = PromptGlossaryContext(project_ref="proj", launch_workspace=None)
    other = PromptGlossaryContext(project_ref="other", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[matching] = None
    app._prompt_glossary_catalogs_by_context[other] = None

    app._refresh_visible_prompt_glossary_surfaces(matching)
    app._refresh_visible_prompt_glossary_surfaces(other)
    app._invalidate_prompt_glossary_catalogs(reason="config")

    assert app.refresh_calls == []
    assert app._pending_selected_agent_semantic_refresh is True

    app._prompt_active = False
    app._flush_pending_selected_agent_semantic_refresh()
    assert app.refresh_calls == [{"render_immediate": False}]
    assert app._pending_selected_agent_semantic_refresh is False

    app._flush_pending_selected_agent_semantic_refresh()
    assert app.refresh_calls == [{"render_immediate": False}]


def test_flush_without_pending_is_noop() -> None:
    """Dismissal with no deferred repaint schedules nothing."""
    app = _CatalogApp(selected=_agent_stub(project="proj"))

    app._flush_pending_selected_agent_semantic_refresh()

    assert app.refresh_calls == []


def test_flush_on_other_tab_drops_pending_without_repaint() -> None:
    """A pending repaint does not fire when dismissal lands off the Agents tab."""
    app = _CatalogApp(
        selected=_agent_stub(project="proj"),
        prompt_active=True,
    )
    context = PromptGlossaryContext(project_ref="proj", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None
    app._refresh_visible_prompt_glossary_surfaces(context)
    assert app._pending_selected_agent_semantic_refresh is True

    app.current_tab = "artifacts"
    app._flush_pending_selected_agent_semantic_refresh()

    assert app.refresh_calls == []
    assert app._pending_selected_agent_semantic_refresh is False


def test_hidden_text_areas_skip_highlight_rebuild() -> None:
    """Hidden or not-displayed bars are skipped by the surface loops."""
    hidden = _area_stub(display=False)
    invisible = _area_stub(visible=False)
    shown = _area_stub()
    app = _CatalogApp(
        selected=_agent_stub(project="proj"),
        areas=[hidden, invisible, shown],
    )
    context = PromptGlossaryContext(project_ref="other", launch_workspace=None)
    app._prompt_glossary_catalogs_by_context[context] = None

    app._refresh_visible_prompt_glossary_surfaces(context)

    assert hidden.calls == []
    assert invisible.calls == []
    assert shown.calls == ["highlight", "refresh"]
    # The mismatched context still skips the detail repaint.
    assert app.refresh_calls == []
