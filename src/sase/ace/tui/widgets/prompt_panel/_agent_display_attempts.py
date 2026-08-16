"""Attempt-history render helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from rich.console import Group
from rich.text import Text

from sase.core.time import get_timezone

from ...models.agent import Agent, AttemptRecord
from ...util.lazy_syntax import lazy_renderable
from ._agent_display_content import (
    get_prompt_content,
    render_attempt_divider,
    render_timestamp_divider,
)
from ._helpers import append_section_heading


def should_render_merged(agent: Agent, attempt_view_mode: str) -> bool:
    """Whether to prepend attempt_history dividers to the reply content."""
    return attempt_view_mode == "merged" and bool(agent.attempt_history)


def render_merged_attempt_history(
    agent: Agent,
    render_markdown: Callable[[str], object],
) -> list[Any]:
    """Render prior attempts followed by the current attempt divider.

    Emits one divider + reply block for each record in ``agent.attempt_history``
    followed by a ``CURRENT`` divider. The caller is responsible for appending
    the current attempt's reply content afterwards.
    """
    renderables: list[Any] = []
    for record in agent.attempt_history:
        renderables.append(render_attempt_divider(record, is_current=False))
        chunks = record.get_timestamped_reply_chunks()
        if chunks:
            for ts, chunk_text in chunks:
                renderables.append(render_timestamp_divider(ts))
                content = chunk_text.strip()
                if content:
                    renderables.append(render_markdown(content))
            continue
        reply = record.get_reply_content()
        if reply and reply.strip():
            renderables.append(render_markdown(reply))
    renderables.append(
        render_attempt_divider(
            None, is_current=True, fallback_model=agent.fallback_model
        )
    )
    return renderables


class AgentAttemptDisplayMixin:
    """Attempt-pinned render path for AgentPromptPanel."""

    def _render_attempt_pinned(self, agent: Agent, attempt_number: int) -> None:
        """Render the prompt panel pinned to a prior attempt.

        Shows the attempt banner (number, timestamp, outcome), the full
        ``error_full`` traceback, the agent prompt (invariant across retries),
        and the archived ``live_reply.md`` for the attempt. Tools/files
        aren't snapshotted per-attempt; the detail panel hides those panels.
        """
        record = find_attempt(agent, attempt_number)
        renderables: list[Any] = []
        if record is None:
            missing = Text()
            missing.append(
                f"Attempt {attempt_number} not found for this agent.\n",
                style="bold #FF5F5F",
            )
            self.update(missing)  # type: ignore[attr-defined]
            return

        renderables.append(
            render_attempt_banner(record, total=len(agent.attempt_history))
        )

        if record.error_full.strip():
            renderables.append(lazy_renderable(record.error_full, "pytb"))
        elif record.error_snippet:
            snippet = Text()
            snippet.append(f"{record.error_snippet}\n", style="#FF5F5F")
            renderables.append(snippet)

        divider = Text()
        divider.append("\n")
        divider.append("─" * 50 + "\n", style="dim")
        divider.append("\n")
        renderables.append(divider)

        prompt_header = Text()
        append_section_heading(prompt_header, "AGENT PROMPT")
        renderables.append(prompt_header)
        prompt_content = get_prompt_content(agent)
        if prompt_content:
            renderables.append(
                self._render_markdown(prompt_content)  # type: ignore[attr-defined]
            )
        else:
            renderables.append(Text("No prompt file found.\n", style="dim italic"))

        reply_header = Text()
        reply_header.append("\n")
        reply_header.append("─" * 50 + "\n", style="dim")
        reply_header.append("\n")
        append_section_heading(
            reply_header,
            f"ATTEMPT {record.attempt_number} REPLY",
            section_id="attempt-reply",
        )
        renderables.append(reply_header)

        chunks = record.get_timestamped_reply_chunks()
        if chunks:
            for ts, chunk_text in chunks:
                renderables.append(render_timestamp_divider(ts))
                content = chunk_text.strip()
                if content:
                    renderables.append(
                        self._render_markdown(content)  # type: ignore[attr-defined]
                    )
        else:
            reply = record.get_reply_content()
            if reply and reply.strip():
                renderables.append(
                    self._render_markdown(reply)  # type: ignore[attr-defined]
                )
            else:
                renderables.append(
                    Text("(no partial reply captured)\n", style="dim italic")
                )

        self.update(Group(*renderables))  # type: ignore[attr-defined]


def find_attempt(agent: Agent, attempt_number: int) -> AttemptRecord | None:
    for record in agent.attempt_history:
        if record.attempt_number == attempt_number:
            return record
    return None


def render_attempt_banner(record: AttemptRecord, *, total: int) -> Text:
    """Render the ``Viewing Attempt N of M`` banner for the pinned view."""
    banner = Text()
    try:
        hhmmss = record.start_hhmmss
    except (ValueError, OSError):
        hhmmss = "??:??:??"
    try:
        end_time = datetime.fromtimestamp(record.end_epoch, get_timezone()).strftime(
            "%H:%M:%S"
        )
    except (ValueError, OSError):
        end_time = "??:??:??"
    banner.append(
        f"Viewing Attempt {record.attempt_number} of {total}",
        style="bold #FF8700",
    )
    banner.append(
        f" · started {hhmmss} · {record.status} at {end_time}\n",
        style="dim #FF8700",
    )
    if record.used_fallback and record.model:
        banner.append(f"Fallback model: {record.model}\n", style="dim #FF8700")
    if record.reason:
        banner.append(f"{record.reason}\n", style="dim #FFAF00")
    banner.append("\n")
    append_section_heading(
        banner,
        "ATTEMPT ERROR",
        style="bold #FF5F5F underline",
        section_id="attempt-error",
    )
    return banner


_find_attempt = find_attempt
_render_attempt_banner = render_attempt_banner
_render_merged_attempt_history = render_merged_attempt_history
_should_render_merged = should_render_merged
