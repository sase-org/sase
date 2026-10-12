"""Prompt text rendering and semantic highlight caches."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from sase.project_display_names import (
    humanize_vcs_refs_in_text,
    project_display_name_map_signature,
)

from ...models.agent import Agent
from ...util.lazy_syntax import (
    LazySyntaxRenderCache,
    exceeds_syntax_highlight_cap,
    lazy_renderable,
)
from ...util.macro_syntax import highlight_markdown_text, highlight_prompt_text
from ._agent_display_hints import clear_agent_hint_render_cache
from ._agent_macro_highlighting import (
    AgentPromptHighlightContext,
    agent_prompt_highlight_context,
)

_HUMANIZED_TEXT_CACHE_LIMIT = 24
_HumanizedTextCacheKey = tuple[int, int, tuple[tuple[str, str], ...], object]
_RAW_PROMPT_HIGHLIGHT_CACHE_LIMIT = 24
_RawPromptHighlightCacheKey = tuple[int, int, tuple[object, ...]]
_AGENT_PROMPT_HIGHLIGHT_CACHE_LIMIT = 24
_AgentPromptHighlightCacheKey = tuple[int, int, tuple[object, ...]]


class AgentPromptDisplayMixin:
    """Render and cache prompt text for an agent detail panel."""

    def _markdown_render_cache(self) -> LazySyntaxRenderCache:
        cache = getattr(self, "_agent_markdown_render_cache", None)
        if cache is None:
            cache = LazySyntaxRenderCache(max_entries=24)
            self._agent_markdown_render_cache = cache
        return cache

    def _reset_markdown_render_cache_for_agent(self, agent: Agent) -> None:
        identity = agent.identity
        previous_identity = getattr(self, "_agent_markdown_render_cache_identity", None)
        if previous_identity != identity:
            cache = getattr(self, "_agent_markdown_render_cache", None)
            if cache is not None:
                cache.clear()
            humanize_cache = getattr(self, "_agent_humanized_text_cache", None)
            if humanize_cache is not None:
                humanize_cache.clear()
            raw_prompt_cache = getattr(self, "_agent_raw_prompt_highlight_cache", None)
            if raw_prompt_cache is not None:
                raw_prompt_cache.clear()
            prompt_cache = getattr(self, "_agent_authored_prompt_highlight_cache", None)
            if prompt_cache is not None:
                prompt_cache.clear()
            clear_agent_hint_render_cache(self)
            self._agent_markdown_render_cache_identity = identity

    def _display_raw_prompt(self, agent: Agent, raw_prompt: str) -> str:
        del agent
        return self._humanize_display_text(raw_prompt)

    def _humanized_text_cache(self) -> dict[_HumanizedTextCacheKey, str]:
        cache = getattr(self, "_agent_humanized_text_cache", None)
        if cache is None:
            cache = {}
            self._agent_humanized_text_cache = cache
        return cache

    def _raw_prompt_highlight_cache(self) -> dict[_RawPromptHighlightCacheKey, Text]:
        cache = getattr(self, "_agent_raw_prompt_highlight_cache", None)
        if cache is None:
            cache = {}
            self._agent_raw_prompt_highlight_cache = cache
        return cache

    def _agent_prompt_highlight_cache(
        self,
    ) -> dict[_AgentPromptHighlightCacheKey, Text]:
        cache = getattr(self, "_agent_authored_prompt_highlight_cache", None)
        if cache is None:
            cache = {}
            self._agent_authored_prompt_highlight_cache = cache
        return cache

    def _prompt_highlight_context(
        self,
        agent: Agent,
        raw_prompt: str = "",
        *,
        schedule: bool = True,
    ) -> AgentPromptHighlightContext:
        return agent_prompt_highlight_context(
            self,
            agent,
            raw_prompt,
            schedule=schedule,
        )

    def _render_raw_prompt(
        self,
        agent: Agent,
        raw_prompt: str,
        humanized_raw_prompt: str,
        *,
        context: AgentPromptHighlightContext | None = None,
    ) -> Text:
        if context is None:
            context = self._prompt_highlight_context(agent, raw_prompt)
        key = (
            len(humanized_raw_prompt),
            hash(humanized_raw_prompt),
            context.fingerprint,
        )
        cache = self._raw_prompt_highlight_cache()
        cached = cache.pop(key, None)
        if cached is not None:
            cache[key] = cached
            return cached

        highlighted = highlight_prompt_text(
            humanized_raw_prompt,
            known_skills=context.known_skills,
            glossary_catalog=context.glossary_catalog,
            repo_catalog=context.repo_catalog,
            semantic_styles=context.styles,
            artifact_ref_known_kinds=context.artifact_ref_known_kinds,
            artifact_ref_styles=context.artifact_ref_styles,
        )
        cache[key] = highlighted
        if len(cache) > _RAW_PROMPT_HIGHLIGHT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        return highlighted

    def _render_agent_prompt(
        self,
        agent: Agent,
        content: str,
        *,
        context: AgentPromptHighlightContext | None = None,
    ) -> RenderableType:
        content = self._humanize_display_text(content)
        if context is None:
            context = self._prompt_highlight_context(
                agent,
                agent.get_raw_prompt_content() or "",
            )
        if not context.has_semantic_catalogs or exceeds_syntax_highlight_cap(
            content,
            "markdown",
        ):
            return lazy_renderable(
                content,
                "markdown",
                render_cache=self._markdown_render_cache(),
            )

        key = (len(content), hash(content), context.fingerprint)
        cache = self._agent_prompt_highlight_cache()
        cached = cache.pop(key, None)
        if cached is not None:
            cache[key] = cached
            return cached

        highlighted = highlight_markdown_text(
            content,
            glossary_catalog=context.glossary_catalog,
            repo_catalog=context.repo_catalog,
            semantic_styles=context.styles,
        )
        cache[key] = highlighted
        if len(cache) > _AGENT_PROMPT_HIGHLIGHT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        return highlighted

    def _humanize_display_text(self, content: str) -> str:
        if "#" not in content:
            return content
        signature = project_display_name_map_signature()
        try:
            from sase.project_tags.catalog import peek_project_tag_catalog_signature

            tag_signature = peek_project_tag_catalog_signature()
        except Exception:
            tag_signature = None
        key = (len(content), hash(content), signature, tag_signature)
        cache = self._humanized_text_cache()
        cached = cache.get(key)
        if cached is not None:
            return cached
        humanized = humanize_vcs_refs_in_text(content)
        cache[key] = humanized
        if len(cache) > _HUMANIZED_TEXT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        return humanized

    def _render_markdown(self, content: str) -> object:
        content = self._humanize_display_text(content)
        return lazy_renderable(
            content,
            "markdown",
            render_cache=self._markdown_render_cache(),
        )
