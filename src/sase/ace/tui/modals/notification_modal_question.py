"""Read-only question preview for the notification modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.ace.tui.actions.agents._notification_navigation import (
    find_agent_for_notification,
)
from sase.ace.tui.provider_styles import (
    provider_model_badge_markup,
    provider_name_style,
)
from sase.notifications import (
    Notification,
    QuestionEntry,
    QuestionSummary,
    build_question_summary,
    format_relative_time,
    is_question_notification,
)
from sase.project_display_names import humanize_cl_name

_QUESTION_CYAN = "#00D7FF"
_AWAITING_GOLD = "#FFD700"
_ANSWERED_GREEN = "#5FD787"
_RULE_COLOR = "#3A526B"


@dataclass(frozen=True)
class _ResolvedAsker:
    name: str
    provider: str | None = None
    model: str | None = None


class NotificationQuestionMixin:
    """Render question notifications as a rich, read-only summary."""

    def _render_question_pane(
        self: Any, notification: Notification
    ) -> tuple[str, RenderableType] | None:
        """Return the question pane title and content for *notification*."""
        if not is_question_notification(notification):
            return None

        summary = build_question_summary(notification)
        if summary is None:
            return None
        asker = self._resolve_asker(notification, summary)

        renderables: list[RenderableType] = [
            _identity_header(notification, summary, asker),
            Text(""),
            _status_line(summary),
        ]
        answer_overview = _answer_overview(summary)
        if answer_overview is not None:
            renderables.extend((answer_overview,))

        if not summary.detail_available:
            renderables.extend((Text(""), _detail_fallback(summary)))

        if summary.questions:
            renderables.append(Rule(style=_RULE_COLOR))
            for index, question in enumerate(summary.questions, start=1):
                if index > 1:
                    renderables.append(Rule(style=_RULE_COLOR))
                renderables.append(_question_block(index, question))

        return "Agent Question", Group(*renderables)

    def _resolve_asker(
        self: Any,
        notification: Notification,
        summary: QuestionSummary,
    ) -> _ResolvedAsker:
        """Resolve the best available asker identity without risking the pane."""
        try:
            agent = find_agent_for_notification(self.app, notification)
        except Exception:
            agent = None

        if agent is not None:
            try:
                display_name = _clean_text(
                    getattr(agent, "agent_name", None)
                ) or _clean_text(getattr(agent, "display_name", None))
                provider = _clean_text(getattr(agent, "llm_provider", None))
                model = _clean_text(getattr(agent, "model", None))
                if display_name is not None:
                    return _ResolvedAsker(display_name, provider, model)
            except Exception:
                pass

        if summary.asker_cl_name:
            try:
                fallback = _clean_text(humanize_cl_name(summary.asker_cl_name))
            except Exception:
                fallback = summary.asker_cl_name
            if fallback:
                return _ResolvedAsker(fallback)
        return _ResolvedAsker("Unknown agent")


def _identity_header(
    notification: Notification,
    summary: QuestionSummary,
    asker: _ResolvedAsker,
) -> Text:
    header = Text("Question from ", style="dim")
    try:
        name_style = provider_name_style(asker.provider)
    except Exception:
        name_style = "bold #AF87D7"
    header.append(asker.name, style=name_style)

    badge = _provider_badge(asker.provider, asker.model)
    if badge:
        header.append("   ")
        header.append_text(badge)

    metadata: list[str] = []
    if summary.asker_cl_name:
        try:
            cl_name = humanize_cl_name(summary.asker_cl_name)
        except Exception:
            cl_name = summary.asker_cl_name
        metadata.append(f"ChangeSpec {cl_name}")
    metadata.append(f"asked {format_relative_time(notification.timestamp)}")
    if summary.session_id:
        metadata.append(f"session {_short_session_id(summary.session_id)}")
    header.append("\n")
    header.append(" · ".join(metadata), style="dim")
    return header


def _provider_badge(provider: str | None, model: str | None) -> Text | None:
    if not provider and not model:
        return None
    try:
        return Text.from_markup(provider_model_badge_markup(provider, model))
    except Exception:
        label = provider.upper() if provider else "MODEL"
        if model:
            label += f"({model})"
        return Text(label, style="bold #AF87D7")


def _status_line(summary: QuestionSummary) -> Table:
    status = Text()
    action = Text(justify="right")
    if summary.answer_state == "awaiting":
        status.append("● Awaiting your answer", style=f"bold {_AWAITING_GOLD}")
        action.append("press Enter to answer", style="bold #87D7FF")
    elif summary.answer_state == "answered":
        status.append("✓ Answered", style=f"bold {_ANSWERED_GREEN}")
        action.append("response recorded", style="dim")
    elif summary.answer_state == "expired":
        status.append("○ Expired or already handled", style="bold dim")
        action.append("request is no longer active", style="dim")
    else:
        status.append("? Details unavailable", style="bold #FFAF5F")
        action.append("request could not be loaded", style="dim")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_column(justify="right")
    table.add_row(status, action)
    return table


def _answer_overview(summary: QuestionSummary) -> Text | None:
    if summary.answer_state != "answered":
        return None

    selected = [
        option.label
        for question in summary.questions
        for option in question.options
        if option.selected
    ]
    custom = [
        question.custom_answer
        for question in summary.questions
        if question.custom_answer
    ]
    if not selected and not custom and not summary.global_note:
        return None

    overview = Text()
    if selected:
        overview.append("You chose: ", style="dim")
        overview.append(", ".join(selected), style=f"bold {_ANSWERED_GREEN}")
    if custom:
        if overview:
            overview.append("\n")
        overview.append("Custom response: ", style="dim")
        overview.append("; ".join(custom))
    if summary.global_note:
        if overview:
            overview.append("\n")
        overview.append("Note: ", style="dim")
        overview.append(summary.global_note, style="italic")
    return overview


def _detail_fallback(summary: QuestionSummary) -> Text:
    fallback = Text()
    if summary.questions:
        fallback.append(
            "Some original question details are unavailable.", style="dim italic"
        )
    else:
        fallback.append(summary.fallback_note or "Question details are unavailable.")
    return fallback


def _question_block(index: int, question: QuestionEntry) -> Group:
    heading = Text()
    heading.append(f"Q{index}", style=f"bold {_QUESTION_CYAN}")
    if question.header:
        heading.append("  ")
        heading.append(question.header, style="bold")

    prompt = Text(question.prompt)
    choices: list[RenderableType] = [heading, prompt]
    if question.options:
        choices.append(Text(""))
        choices.extend(_option_line(option) for option in question.options)
    if question.custom_answer:
        custom = Text("  ✎ Custom", style=f"bold {_ANSWERED_GREEN}")
        custom.append(" — ", style="dim")
        custom.append(question.custom_answer)
        choices.append(custom)

    mode = "multi-select" if question.multi_select else "single-select"
    choices.extend((Text(""), Text(mode, style="dim italic")))
    return Group(*choices)


def _option_line(option: Any) -> Text:
    selected = bool(option.selected)
    marker = "●" if selected else "○"
    marker_style = f"bold {_ANSWERED_GREEN}" if selected else "dim"
    label_style = f"bold {_ANSWERED_GREEN}" if selected else "bold"
    line = Text("  ")
    line.append(marker, style=marker_style)
    line.append(" ")
    line.append(option.label, style=label_style)
    if option.description:
        line.append(" — ", style="dim")
        line.append(option.description, style="dim")
    return line


def _short_session_id(session_id: str) -> str:
    return session_id if len(session_id) <= 8 else f"{session_id[:8]}…"


def _clean_text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None
