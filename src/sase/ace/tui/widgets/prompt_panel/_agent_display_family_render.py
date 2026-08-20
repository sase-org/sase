"""Family-specific render paths for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_agent_reply_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_family import (
    effective_family_fold_level,
    family_member_rows,
)
from ._agent_display_header import AgentHeader
from ._agent_display_state import HeaderHintState
from ._agent_monitor_section import MonitorTextAnnotator, build_monitor_phase
from ._agent_xprompt_highlighting import (
    AgentPromptHighlightContext,
    agent_prompt_highlight_context,
    apply_authored_prompt_overlays,
)
from ._container_hint_text import container_text_with_file_hints
from ._fold_language import fold_count_style
from ._file_path_hints import (
    has_file_path,
    resolve_agent_workspace_dir,
)
from ._hint_caps import HintContentBudget
from ._helpers import (
    PROMPT_PANEL_SECTION_HEADING_STYLE,
    append_section_heading,
)


class AgentFamilyDisplayMixin:
    """Render family sections and their file-hint variants."""

    if TYPE_CHECKING:

        def _display_raw_xprompt(self, agent: Agent, raw_xprompt: str) -> str: ...

        def _humanize_display_text(self, content: str) -> str: ...

        def _render_markdown(self, content: str) -> object: ...

        def _render_xprompt(
            self,
            agent: Agent,
            raw_xprompt: str,
            humanized_xprompt: str,
            *,
            context: AgentPromptHighlightContext | None = None,
        ) -> Text: ...

        def _render_agent_prompt(
            self,
            agent: Agent,
            content: str,
            *,
            context: AgentPromptHighlightContext | None = None,
        ) -> RenderableType: ...

    def _update_family_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None,
        *,
        panel_level: object,
        section_fold_overrides: object,
        hint_state: HeaderHintState | None = None,
    ) -> None:
        """Render a family container and its always-open conversation.

        Family metadata still follows the shared two-level fold, while xprompt,
        prompt, and reply bodies remain fully visible at every level.
        ``hint_state`` only changes how that content is annotated.
        """
        shared_level = (
            panel_level if isinstance(panel_level, FoldLevel) else FoldLevel.COLLAPSED
        )
        level = effective_family_fold_level("", shared_level)
        overrides = (
            section_fold_overrides
            if isinstance(section_fold_overrides, Mapping)
            else {}
        )
        renderables: list[Any] = [header_text]
        hint_budget = HintContentBudget() if hint_state is not None else None

        error_level = effective_family_fold_level("error", level, overrides)
        if error_tb_syntax is not None and error_level != FoldLevel.COLLAPSED:
            renderables.append(error_tb_syntax)

        rendered_content_section = False
        raw_xprompt = agent.get_raw_xprompt_content()
        highlight_context = agent_prompt_highlight_context(
            self,
            agent,
            raw_xprompt or "",
        )
        if raw_xprompt:
            append_section_heading(header_text, "AGENT XPROMPT")
            humanized_xprompt = self._display_raw_xprompt(agent, raw_xprompt)
            xprompt = (
                self._render_xprompt(
                    agent,
                    raw_xprompt,
                    humanized_xprompt,
                    context=highlight_context,
                )
                if hint_state is None
                else Text(humanized_xprompt)
            )
            if hint_state is None:
                header_text.append_text(xprompt)
            else:
                header_text.append_text(
                    self._family_text_with_hints(
                        xprompt,
                        hint_state,
                        workspace_dir=hint_state.workspace_dir,
                        budget=hint_budget,
                        xprompt_agent=agent,
                        raw_xprompt=raw_xprompt,
                        semantic_context=highlight_context,
                    )
                )
            header_text.append("\n")
            rendered_content_section = True

        prompt_content = get_prompt_content(agent)
        if prompt_content:
            if rendered_content_section:
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
            append_section_heading(header_text, "AGENT PROMPT")
            if hint_state is None:
                renderables.append(
                    self._render_agent_prompt(
                        agent,
                        prompt_content,
                        context=highlight_context,
                    )
                )
            else:
                renderables.append(
                    self._family_text_with_hints(
                        self._humanize_display_text(prompt_content),
                        hint_state,
                        workspace_dir=hint_state.workspace_dir,
                        budget=hint_budget,
                        semantic_context=highlight_context,
                    )
                )
            rendered_content_section = True

        reply_header = Text()
        if rendered_content_section:
            reply_header.append("\n")
            reply_header.append("\u2500" * 50 + "\n", style="dim")
            reply_header.append("\n")
        phases = family_member_rows(agent)
        reply_heading = Text(
            "AGENT REPLY",
            style=PROMPT_PANEL_SECTION_HEADING_STYLE,
        )
        reply_heading.append(
            f" · {len(phases)}",
            style=fold_count_style("AGENT REPLY"),
        )
        append_section_heading(reply_header, reply_heading)
        renderables.append(reply_header)
        for phase in phases:
            if phase.is_monitor:
                renderables.extend(
                    build_monitor_phase(
                        phase,
                        annotate=(
                            None
                            if hint_state is None
                            else self._monitor_phase_annotator(
                                phase, hint_state, hint_budget
                            )
                        ),
                    )
                )
                continue
            renderables.append(
                render_phase_divider(
                    get_phase_label(phase),
                    phase.run_start_time or phase.start_time,
                )
            )
            if hint_state is None:
                reply_renderables = render_agent_reply_content(
                    phase,
                    self._render_markdown,
                )
            else:
                reply_renderables = self._family_reply_renderables_with_hints(
                    phase,
                    hint_state,
                    budget=hint_budget,
                )
            renderables.extend(
                reply_renderables
                or [
                    Text(
                        "No response content yet.\n",
                        style="dim italic",
                    )
                ]
            )

        renderable: object = Group(*renderables)
        if hint_state is not None:
            prepare_hint_renderable = getattr(
                self,
                "_prepare_cached_hint_renderable",
                None,
            )
            if callable(prepare_hint_renderable):
                renderable = prepare_hint_renderable(renderable)
        self.update(renderable)  # type: ignore[attr-defined]

    def _family_text_with_hints(
        self,
        content: str | Text,
        hint_state: HeaderHintState,
        *,
        workspace_dir: str | None,
        budget: HintContentBudget | None,
        xprompt_agent: Agent | None = None,
        raw_xprompt: str | None = None,
        semantic_context: AgentPromptHighlightContext | None = None,
    ) -> Text:
        """Return one visible family content fragment with numbered paths."""
        text = container_text_with_file_hints(
            content,
            hint_state,
            workspace_dir=workspace_dir,
            budget=budget,
        )
        include_xprompt = xprompt_agent is not None and raw_xprompt is not None
        context = semantic_context
        if context is None and include_xprompt and xprompt_agent is not None:
            context = agent_prompt_highlight_context(
                self,
                xprompt_agent,
                raw_xprompt or "",
            )
        if context is None:
            return text

        hint_spans = tuple(text.spans)
        apply_authored_prompt_overlays(
            text,
            text.plain,
            context,
            include_xprompt=include_xprompt,
            hint_spans=hint_spans,
        )
        return text

    @staticmethod
    def _family_member_hint_workspace(agent: Agent, content: str) -> str | None:
        """Resolve a phase workspace only when its visible text has a path."""
        if not has_file_path(content):
            return None
        return resolve_agent_workspace_dir(
            agent.effective_workspace_num,
            agent.project_file,
            agent.workspace_dir,
        )

    def _monitor_phase_annotator(
        self,
        phase: Agent,
        hint_state: HeaderHintState,
        budget: HintContentBudget | None,
    ) -> MonitorTextAnnotator:
        """Annotate a monitor command or log against the phase workspace."""

        def annotate(content: str | Text) -> Text:
            text = content if isinstance(content, Text) else Text(content)
            return self._family_text_with_hints(
                text,
                hint_state,
                workspace_dir=self._family_member_hint_workspace(phase, text.plain),
                budget=budget,
            )

        return annotate

    def _family_reply_renderables_with_hints(
        self,
        agent: Agent,
        hint_state: HeaderHintState,
        *,
        budget: HintContentBudget | None,
    ) -> list[object]:
        """Render one fully-open family phase reply with phase-local hints."""
        renderables: list[object] = []
        chunks = agent.get_timestamped_reply_chunks()
        if chunks:
            visible_chunks = [
                (
                    timestamp,
                    self._humanize_display_text(chunk_text.strip())
                    if chunk_text.strip()
                    else "",
                )
                for timestamp, chunk_text in chunks
            ]
            workspace_dir = self._family_member_hint_workspace(
                agent,
                "\n".join(content for _timestamp, content in visible_chunks),
            )
            for timestamp, content in visible_chunks:
                renderables.append(render_timestamp_divider(timestamp))
                if content:
                    renderables.append(
                        self._family_text_with_hints(
                            content,
                            hint_state,
                            workspace_dir=workspace_dir,
                            budget=budget,
                        )
                    )
            return renderables

        reply_content = (
            agent.get_live_reply_content()
            or agent.get_response_content()
            or agent.get_chat_response_content()
        )
        if reply_content:
            reply_content = self._humanize_display_text(reply_content)
            renderables.append(
                self._family_text_with_hints(
                    reply_content,
                    hint_state,
                    workspace_dir=self._family_member_hint_workspace(
                        agent,
                        reply_content,
                    ),
                    budget=budget,
                )
            )
        return renderables
