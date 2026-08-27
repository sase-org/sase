"""Reply and free-form text annotators shared by file-hint agent documents."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text

from ...models.agent import Agent
from ._agent_display_content import render_timestamp_divider
from ._agent_display_header import AgentHeader
from ._agent_gate_section import GateTextAnnotator
from ._agent_monitor_section import MonitorTextAnnotator
from ._agent_proc_shell_section import ProcShellTextAnnotator
from ._hint_caps import append_bounded_text_with_file_hints


def render_reply_with_hints(
    agent: Agent,
    target: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    humanize_text: Callable[[str], str],
) -> int:
    """Render one agent's reply content with file hints into a Text."""
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            target.append_text(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                content = humanize_text(content)
                hint_counter = append_bounded_text_with_file_hints(
                    target,
                    content + "\n",
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                )
                target.append("\n")
        return hint_counter
    live_reply = agent.get_live_reply_content()
    if live_reply:
        live_reply = humanize_text(live_reply)
        return append_bounded_text_with_file_hints(
            target,
            live_reply + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    response_content = agent.get_response_content()
    if response_content:
        response_content = humanize_text(response_content)
        return append_bounded_text_with_file_hints(
            target,
            response_content + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    return hint_counter


def hint_monitor_annotator(
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> tuple[MonitorTextAnnotator, Callable[[], int]]:
    """Annotate free-form monitor text and expose the updated hint counter."""

    def annotate(content: str | Text) -> Text:
        nonlocal hint_counter
        target = Text(end="")
        raw = content.plain if isinstance(content, Text) else content
        hint_counter = append_bounded_text_with_file_hints(
            target,
            raw,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
        return target

    return annotate, lambda: hint_counter


def hint_gate_annotator(
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> tuple[GateTextAnnotator, Callable[[], int]]:
    """Annotate free-form gate text and expose the updated hint counter."""

    def annotate(content: str | Text) -> Text:
        nonlocal hint_counter
        target = Text(end="")
        raw = content.plain if isinstance(content, Text) else content
        hint_counter = append_bounded_text_with_file_hints(
            target,
            raw,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
        return target

    return annotate, lambda: hint_counter


def hint_proc_shell_annotator(
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> tuple[ProcShellTextAnnotator, Callable[[], int]]:
    """Annotate free-form proc-shell text and expose the updated hint counter."""

    def annotate(content: str | Text) -> Text:
        nonlocal hint_counter
        target = Text(end="")
        raw = content.plain if isinstance(content, Text) else content
        hint_counter = append_bounded_text_with_file_hints(
            target,
            raw,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
        return target

    return annotate, lambda: hint_counter
