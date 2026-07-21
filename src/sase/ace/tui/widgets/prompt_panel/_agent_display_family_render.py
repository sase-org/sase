"""Family-specific render paths for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ...util.xprompt_syntax import apply_xprompt_overlays
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_agent_reply_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_family import (
    FAMILY_PROMPT_SECTION_ID,
    FAMILY_REPLY_SECTION_ID,
    FAMILY_XPROMPT_SECTION_ID,
    append_family_fold_heading,
    bounded_content_preview,
    effective_family_fold_level,
    family_member_rows,
    reply_tail_preview,
)
from ._agent_display_header import AgentHeader
from ._agent_display_state import HeaderHintState
from ._agent_xprompt_highlighting import known_xprompt_skill_names
from ._file_path_hints import (
    FILE_PATH_RE,
    append_text_with_file_hints,
    resolve_agent_workspace_dir,
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
        ) -> Text: ...

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
        """Render every family section at its effective two-level fold.

        ``hint_state`` only changes how already-visible content is annotated;
        both normal and hint mode intentionally share this layout path.
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

        error_level = effective_family_fold_level("error", level, overrides)
        if error_tb_syntax is not None and error_level != FoldLevel.COLLAPSED:
            renderables.append(error_tb_syntax)

        rendered_content_section = False
        raw_xprompt = agent.get_raw_xprompt_content()
        if raw_xprompt:
            xprompt_level = effective_family_fold_level(
                FAMILY_XPROMPT_SECTION_ID,
                level,
                overrides,
            )
            append_family_fold_heading(
                header_text,
                "AGENT XPROMPT",
                section_id=FAMILY_XPROMPT_SECTION_ID,
                level=xprompt_level,
            )
            humanized_xprompt = self._display_raw_xprompt(agent, raw_xprompt)
            if xprompt_level == FoldLevel.EXPANDED:
                xprompt = bounded_content_preview(humanized_xprompt)
            else:
                xprompt = (
                    self._render_xprompt(
                        agent,
                        raw_xprompt,
                        humanized_xprompt,
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
                        xprompt_agent=agent,
                        raw_xprompt=raw_xprompt,
                    )
                )
            if xprompt_level != FoldLevel.EXPANDED:
                header_text.append("\n")
            rendered_content_section = True

        prompt_content = get_prompt_content(agent)
        if prompt_content:
            if rendered_content_section:
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
            prompt_level = effective_family_fold_level(
                FAMILY_PROMPT_SECTION_ID,
                level,
                overrides,
            )
            append_family_fold_heading(
                header_text,
                "AGENT PROMPT",
                section_id=FAMILY_PROMPT_SECTION_ID,
                level=prompt_level,
            )
            if prompt_level == FoldLevel.EXPANDED:
                prompt = bounded_content_preview(
                    self._humanize_display_text(prompt_content)
                )
                if hint_state is None:
                    header_text.append_text(prompt)
                else:
                    header_text.append_text(
                        self._family_text_with_hints(
                            prompt,
                            hint_state,
                            workspace_dir=hint_state.workspace_dir,
                        )
                    )
            else:
                if hint_state is None:
                    renderables.append(self._render_markdown(prompt_content))
                else:
                    renderables.append(
                        self._family_text_with_hints(
                            self._humanize_display_text(prompt_content),
                            hint_state,
                            workspace_dir=hint_state.workspace_dir,
                        )
                    )
            rendered_content_section = True

        reply_header = Text()
        if rendered_content_section:
            reply_header.append("\n")
            reply_header.append("\u2500" * 50 + "\n", style="dim")
            reply_header.append("\n")
        reply_level = effective_family_fold_level(
            FAMILY_REPLY_SECTION_ID,
            level,
            overrides,
        )
        phases = family_member_rows(agent)
        append_family_fold_heading(
            reply_header,
            "AGENT REPLY",
            section_id=FAMILY_REPLY_SECTION_ID,
            level=reply_level,
            count=len(phases),
        )
        if reply_level == FoldLevel.EXPANDED:
            renderables.append(reply_header)
            for phase in phases:
                renderables.append(
                    render_phase_divider(
                        get_phase_label(phase),
                        phase.run_start_time or phase.start_time,
                    )
                )
                reply_preview = reply_tail_preview(self._family_reply_text(phase))
                if hint_state is None:
                    renderables.append(reply_preview)
                else:
                    renderables.append(
                        self._family_text_with_hints(
                            reply_preview,
                            hint_state,
                            workspace_dir=self._family_member_hint_workspace(
                                phase,
                                reply_preview.plain,
                            ),
                        )
                    )
        else:
            renderables.append(reply_header)
            for phase in phases:
                renderables.append(
                    render_phase_divider(
                        get_phase_label(phase),
                        phase.run_start_time or phase.start_time,
                    )
                )
                if hint_state is None:
                    renderables.extend(
                        render_agent_reply_content(phase, self._render_markdown)
                    )
                else:
                    renderables.extend(
                        self._family_reply_renderables_with_hints(
                            phase,
                            hint_state,
                        )
                    )

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def _family_text_with_hints(
        self,
        content: str | Text,
        hint_state: HeaderHintState,
        *,
        workspace_dir: str | None,
        xprompt_agent: Agent | None = None,
        raw_xprompt: str | None = None,
    ) -> Text:
        """Return one visible family content fragment with numbered paths."""
        source = content if isinstance(content, Text) else Text(content)
        source_text = source.plain
        counter = hint_state.hint_counter
        insertions = tuple(
            (
                match.start(1) if match.group(1) else match.start(2),
                len(f"[{counter + index}] "),
            )
            for index, match in enumerate(FILE_PATH_RE.finditer(source_text))
        )
        text = Text(style=source.style)
        hint_state.hint_counter = append_text_with_file_hints(
            text,
            source_text,
            hint_state.hint_counter,
            hint_state.hint_mappings,
            workspace_dir,
        )
        for span in source.spans:
            start = span.start + sum(
                width for position, width in insertions if position <= span.start
            )
            end = span.end + sum(
                width for position, width in insertions if position < span.end
            )
            text.stylize(span.style, start, end)
        if xprompt_agent is None or raw_xprompt is None:
            return text

        hint_spans = list(text.spans)
        try:
            apply_xprompt_overlays(
                text,
                text.plain,
                known_skills=known_xprompt_skill_names(
                    self,
                    xprompt_agent,
                    raw_xprompt,
                ),
            )
            for span in hint_spans:
                text.stylize(span.style, span.start, span.end)
        except Exception:
            pass
        return text

    @staticmethod
    def _family_member_hint_workspace(agent: Agent, content: str) -> str | None:
        """Resolve a phase workspace only when its visible text has a path."""
        if FILE_PATH_RE.search(content) is None:
            return None
        return resolve_agent_workspace_dir(
            agent.effective_workspace_num,
            agent.project_file,
            agent.workspace_dir,
        )

    def _family_reply_renderables_with_hints(
        self,
        agent: Agent,
        hint_state: HeaderHintState,
    ) -> list[object]:
        """Render one fully-open family phase reply with phase-local hints."""
        renderables: list[object] = []
        chunks = agent.get_timestamped_reply_chunks()
        if chunks:
            for timestamp, chunk_text in chunks:
                renderables.append(render_timestamp_divider(timestamp))
                content = chunk_text.strip()
                if content:
                    content = self._humanize_display_text(content)
                    renderables.append(
                        self._family_text_with_hints(
                            content,
                            hint_state,
                            workspace_dir=self._family_member_hint_workspace(
                                agent,
                                content,
                            ),
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
                )
            )
        return renderables

    @staticmethod
    def _family_reply_text(agent: Agent) -> str:
        """Load one phase reply for an expanded tail preview."""
        chunks = agent.get_timestamped_reply_chunks()
        if chunks:
            return "\n".join(chunk for _timestamp, chunk in chunks if chunk.strip())
        live_reply = agent.get_live_reply_content()
        if live_reply:
            return live_reply
        response = agent.get_response_content()
        if response:
            return response
        chat_response = agent.get_chat_response_content()
        return chat_response or ""
