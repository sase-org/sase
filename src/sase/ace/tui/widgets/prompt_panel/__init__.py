"""Agent prompt panel widget for sase's TUI."""

from typing import Any

from rich.console import Group

from ...models.agent import Agent
from ...llm_calls import supports_slow_tool_sources
from ...llm_calls.cache import slow_tool_sources_have_pending
from ._agent_display import AgentDisplayMixin
from ._agent_display_hints import AgentHintsDisplayMixin
from ._helpers import (
    aggregate_meta_fields,
    extract_meta_fields,
    format_meta_key,
    load_xprompts_used,
)
from ._identity_header import (
    IdentityHeader,
    IdentityHeaderSink,
    MemberJumpMapSink,
    find_identity_header,
    find_member_jump_map,
    find_member_roster,
)
from ...util.renderable_digest import renderable_content_digest
from ..decks.card_part import flatten_card_document
from ._section_view import SectionViewMixin
from ._workflow_display import WorkflowDisplayMixin

_SLOW_TOOL_RENDER_TICK_SECONDS = 5.0


class AgentPromptPanel(
    SectionViewMixin, AgentDisplayMixin, AgentHintsDisplayMixin, WorkflowDisplayMixin
):
    """Top panel showing agent details and the input prompt."""

    def _section_view_features_enabled(self) -> bool:
        """Zoom modal panels keep today's behavior; only the main panel gates."""
        return getattr(self, "id", None) == "agent-prompt-panel"

    _identity_header_sink: IdentityHeaderSink | None = None
    _detach_xprompt: bool = False
    _identity_last_published: IdentityHeader | None = None
    _identity_last_content: Any = ""
    _member_jump_map_sink: MemberJumpMapSink | None = None
    _jump_map_last_published: Any = None
    _member_roster_last_published: Any = None
    _main_document_sink: Any | None = None
    _main_document_partial: bool = False

    def attach_identity_header_sink(
        self,
        sink: IdentityHeaderSink | None,
        *,
        detach_xprompt: bool = False,
    ) -> None:
        """Publish detached identity headers to ``sink`` on each update."""
        self._identity_header_sink = sink
        self._detach_xprompt = sink is not None and detach_xprompt

    @property
    def detaches_identity_header(self) -> bool:
        """Whether builders should split the identity out of documents."""
        return self._identity_header_sink is not None

    @property
    def detaches_xprompt(self) -> bool:
        """Whether xprompts travel with the detached identity header."""
        return self.detaches_identity_header and self._detach_xprompt

    def attach_member_jump_map_sink(self, sink: MemberJumpMapSink | None) -> None:
        """Publish carried jump maps to ``sink`` on each update."""
        self._member_jump_map_sink = sink

    def inline_document_renderable(self) -> Any:
        """Return the current document with its identity inlined on top."""
        from rich.text import Text

        identity = getattr(self, "_identity_last_published", None)
        content = flatten_card_document(getattr(self, "_identity_last_content", ""))
        roster = getattr(self, "_member_roster_last_published", None)
        if identity is None:
            if roster is None:
                return content
            if isinstance(content, Text):
                combined = Text()
                combined.append_text(content)
                if combined.plain and not combined.plain.endswith("\n"):
                    combined.append("\n")
                combined.append("\n")
                combined.append_text(roster)
                return combined
            return Group(content, Text("\n"), roster)  # type: ignore[arg-type]
        if roster is None:
            return Group(identity.inline_renderable(), content)  # type: ignore[arg-type]
        if isinstance(content, Text):
            combined_body = Text()
            combined_body.append_text(content)
            if combined_body.plain and not combined_body.plain.endswith("\n"):
                combined_body.append("\n")
            combined_body.append("\n")
            combined_body.append_text(roster)
            return Group(identity.inline_renderable(), combined_body)  # type: ignore[arg-type]
        return Group(identity.inline_renderable(), content, Text("\n"), roster)  # type: ignore[arg-type]

    def prepare_section_document_for_agent(self, agent: Agent) -> None:
        """Select the regular or attempt-pinned document for ``agent``."""
        self.prepare_section_document(
            (agent.identity, getattr(self, "attempt_pinned_number", None))
        )

    def attach_main_document_sink(self, sink: Any | None) -> None:
        """Attach the deck-mode Main document sink."""
        self._main_document_sink = sink

    def update_header_only(self, agent: Agent) -> None:
        """Render only the header, marking the Main document partial."""
        self._main_document_partial = True
        try:
            super().update_header_only(agent)
        finally:
            self._main_document_partial = False

    def update(self, content: Any = "", *, layout: bool = True) -> None:
        """Update content while invalidating only the cached rendered anchors."""
        sink = getattr(self, "_identity_header_sink", None)
        if sink is not None:
            self._identity_last_published = find_identity_header(content)
            self._identity_last_content = content
            sink(self._identity_last_published)
        jump_sink = getattr(self, "_member_jump_map_sink", None)
        if jump_sink is not None:
            self._jump_map_last_published = find_member_jump_map(content)
            self._member_roster_last_published = find_member_roster(content)
            jump_sink(
                self._jump_map_last_published,
                self._member_roster_last_published,
            )
        digest: str | None
        try:
            digest = renderable_content_digest(content)
        except Exception:
            digest = None
        applied = self._apply_section_content(
            flatten_card_document(content), digest, layout=layout
        )
        if applied:
            main_sink = getattr(self, "_main_document_sink", None)
            if callable(main_sink):
                try:
                    main_sink(
                        content,
                        bool(getattr(self, "_main_document_partial", False)),
                        digest,
                    )
                except Exception:
                    pass

    def _configure_slow_tool_render_tick(self, agent: Agent) -> None:
        if getattr(self, "_agent_hint_mode_rendered", False):
            self._cancel_slow_tool_render_tick()
            return
        if self.attempt_pinned_number is not None:
            self._cancel_slow_tool_render_tick()
            return
        if not supports_slow_tool_sources(agent) or not slow_tool_sources_have_pending(
            agent
        ):
            self._cancel_slow_tool_render_tick()
            return
        if (
            self._slow_tool_render_timer is not None
            and self._slow_tool_tick_agent is not None
            and self._slow_tool_tick_agent.identity == agent.identity
        ):
            self._slow_tool_tick_agent = agent
            return

        self._cancel_slow_tool_render_tick()
        self._slow_tool_tick_agent = agent
        try:
            self._slow_tool_render_timer = self.set_interval(
                _SLOW_TOOL_RENDER_TICK_SECONDS,
                self._on_slow_tool_render_tick,
            )
        except Exception:
            self._slow_tool_tick_agent = None

    def _cancel_slow_tool_render_tick(self) -> None:
        if self._slow_tool_render_timer is not None:
            self._slow_tool_render_timer.stop()
            self._slow_tool_render_timer = None
        self._slow_tool_tick_agent = None

    def _on_slow_tool_render_tick(self) -> None:
        if getattr(self, "_agent_hint_mode_rendered", False):
            self._cancel_slow_tool_render_tick()
            return
        agent = self._slow_tool_tick_agent
        if agent is None:
            self._cancel_slow_tool_render_tick()
            return
        if not slow_tool_sources_have_pending(agent):
            self._cancel_slow_tool_render_tick()
            return
        if self._navigation_gate_is_active():
            return
        context = getattr(self, "_agent_detail_render_context", None)
        if context is not None and not context.is_current(
            agent.identity,
            context.generation,
            context.attempt_view_mode,
            context.attempt_pinned_number,
        ):
            self._cancel_slow_tool_render_tick()
            return
        refresh = getattr(self, "refresh_slow_tool_metadata_from_cache", None)
        if callable(refresh):
            refresh(agent)

    def _navigation_gate_is_active(self) -> bool:
        try:
            app = self.app
        except Exception:
            return False
        gate = getattr(app, "_nav_gate", None)
        is_navigating = getattr(gate, "is_navigating", None)
        return bool(callable(is_navigating) and is_navigating())

    def on_unmount(self) -> None:
        self._cancel_slow_tool_render_tick()


__all__ = [
    "AgentPromptPanel",
    "aggregate_meta_fields",
    "extract_meta_fields",
    "format_meta_key",
    "load_xprompts_used",
]
