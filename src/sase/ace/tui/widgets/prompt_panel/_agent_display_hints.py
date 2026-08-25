"""Agent display with file-path hints for the agent prompt panel."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...util.lazy_syntax import CachedRenderable
from ...util.trace import tui_trace
from ._agent_clan_aggregation import prepare_clan_section_snapshot
from ._agent_display_hint_cache import (
    AgentHintRenderCacheEntry,
    AgentHintRenderCacheKey,
    agent_hint_render_cache,
    agent_hint_render_cache_key,
    clear_agent_hint_render_cache,
    trim_agent_hint_render_cache,
)
from ._agent_display_hint_render import AgentHintRenderMixin
from ._agent_display_header_summary import (
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_state import AgentHintRender
from ._file_path_hints import (
    annotated_char_scope,
    clear_file_hint_resolution_caches,
)


def _plain_renderable_content(renderable: object) -> str:
    """Flatten the hint document for introspection without rendering it."""
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(
            _plain_renderable_content(child) for child in renderable.renderables
        )
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(renderable)


class AgentHintsDisplayMixin(AgentHintRenderMixin):
    """Mixin providing hint-annotated agent display for AgentPromptPanel."""

    _agent_hint_renderable: CachedRenderable | None = None
    _rendered_agent_hint_cache_key: AgentHintRenderCacheKey | None = None

    def hint_document_is_current(self, agent: Agent) -> bool:
        """Return whether the visible annotated document matches ``agent``."""
        if not getattr(self, "_agent_hint_mode_rendered", False):
            return False
        rendered_key = getattr(self, "_rendered_agent_hint_cache_key", None)
        return rendered_key is not None and rendered_key == agent_hint_render_cache_key(
            self, agent
        )

    def _prepare_cached_hint_renderable(
        self,
        renderable: RenderableType,
    ) -> CachedRenderable:
        """Wrap and retain a newly built hint document's segment cache."""
        cached = CachedRenderable(
            renderable,
            _plain_renderable_content(renderable),
        )
        self._agent_hint_renderable = cached
        return cached

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Render the agent display with hints and trace the keystroke path.

        The span carries the counters a view-hints capture needs to apportion
        cost: how much text was annotated, how many hints came out, and whether
        the render ran against a warm or cold detail-header summary.
        """
        prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
        if callable(prepare_sections):
            prepare_sections(agent)
        if agent.is_clan_container:
            prepare_clan_section_snapshot(self, agent)
        self._reset_markdown_render_cache_for_agent(agent)  # type: ignore[attr-defined]
        cache_key = agent_hint_render_cache_key(self, agent)
        cache = agent_hint_render_cache(self)
        with (
            tui_trace(
                "widget.prompt_panel.update_display_with_hints",
                family_container=agent.is_family_container_row,
                clan_container=agent.is_clan_container,
            ) as extra,
            annotated_char_scope() as annotated_chars,
        ):
            cached = cache.get(cache_key)
            if cached is not None:
                cache.move_to_end(cache_key)
                self._agent_hint_mode_rendered = True  # type: ignore[attr-defined]
                self._agent_hint_renderable = cached.renderable
                cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
                if callable(cancel_slow_tick):
                    cancel_slow_tick()
                summary = get_cached_detail_header_summary(self, agent)
                if summary is not None:
                    publish_opened_workspaces_cache(
                        self,
                        agent,
                        summary.opened_workspaces,
                    )
                self.update(cached.renderable)  # type: ignore[attr-defined]
                if cached.result.header_enrichment_pending:
                    if agent.is_clan_container:
                        self._start_clan_section_enrichment_from_context(agent)  # type: ignore[attr-defined]
                    else:
                        self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
                extra["cache"] = "hit"
                render = cached.result
            else:
                clear_file_hint_resolution_caches()
                self._agent_hint_renderable = None
                render = self._update_display_with_hints_impl(agent)
                renderable = getattr(self, "_agent_hint_renderable", None)
                if isinstance(renderable, CachedRenderable):
                    cache[cache_key] = AgentHintRenderCacheEntry(
                        result=render,
                        renderable=renderable,
                    )
                    cache.move_to_end(cache_key)
                    trim_agent_hint_render_cache(cache)
                extra["cache"] = "miss"
            extra["hints"] = len(render.file_hints)
            extra["commit_views"] = len(render.commit_views)
            extra["tool_call_reports"] = len(render.tool_call_reports)
            extra["memory_reports"] = len(render.memory_reports)
            extra["header_summary"] = (
                "cold" if render.header_enrichment_pending else "warm"
            )
            extra["annotated_chars"] = annotated_chars[0]
            self._rendered_agent_hint_cache_key = cache_key
            return render


__all__ = ["AgentHintsDisplayMixin", "clear_agent_hint_render_cache"]
