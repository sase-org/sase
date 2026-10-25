"""QUESTIONS section mount for the agent prompt panel header.

Renders the session's ``/sase_questions`` rounds on the Main deck's Context
card, ahead of OUTPUT VARIABLES. When the ``questions`` lane has resolved,
the body comes from the lane's :class:`NumberedQuestionRound` values through
the Rich presenter; otherwise a zero-I/O first paint shows one dim line per
in-scope round from :func:`question_round_stubs`. No section renders when
the scope holds no question rows.

Everything imported here at module level stays inside the TUI startup
closure (see ``test_app_import_budget``): the presenter, the scoping
helpers, and the clock arrive through use-site imports.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text

from ...models.agent import Agent
from ...models.fold_state import FoldLevel

if TYPE_CHECKING:
    from ._agent_display_state import DetailHeaderSummary

#: Section identity for fold anchors (``za``/``zA``) and deck search.
QUESTIONS_SECTION_ID = "questions"
_QUESTIONS_TITLE = "QUESTIONS"
_COLOR_HEADER = "bold #D7AF5F underline"


def append_agent_questions_section(
    text: Text,
    agent: Agent,
    *,
    summary: DetailHeaderSummary | None = None,
    fold_level: FoldLevel | None = None,
    now: datetime | None = None,
) -> None:
    """Append the QUESTIONS section for *agent*'s in-scope question rounds.

    A container row sees every session round; a question gate row sees its
    own round; any other turn sees the rounds it asked. *fold_level* is the
    already-resolved session-fold level for container rows and ``None`` for
    any other row, mirroring :func:`append_agent_output_variables_section`.
    """
    if summary is not None and "questions" in summary.ready_lanes:
        rounds = summary.question_rounds
        if not rounds:
            return
        from sase.core.time import local_now

        from ._agent_questions_render import (
            question_rounds_heading_suffix,
            render_question_rounds,
        )

        _append_heading(text, question_rounds_heading_suffix(rounds), fold_level)
        if fold_level == FoldLevel.COLLAPSED:
            return
        level = fold_level if fold_level is not None else FoldLevel.EXPANDED
        text.append_text(
            render_question_rounds(
                rounds,
                level=level,
                now=now if now is not None else local_now(),
            )
        )
        return
    from ...models.agent_question_rounds import question_round_stubs

    from ._agent_questions_render import (
        question_rounds_heading_suffix,
        render_question_stub_lines,
    )

    stubs = question_round_stubs(agent)
    if not stubs:
        return
    _append_heading(text, question_rounds_heading_suffix(stubs), fold_level)
    if fold_level == FoldLevel.COLLAPSED:
        return
    text.append_text(render_question_stub_lines(stubs))


def _append_heading(
    text: Text,
    suffix: Text,
    fold_level: FoldLevel | None,
) -> None:
    """Append the divider plus the QUESTIONS heading carrying *suffix*."""
    from ._agent_display_agent_session import append_agent_session_fold_heading
    from ._helpers import append_major_section_divider, append_section_heading

    append_major_section_divider(text)
    if fold_level is not None:
        plain = suffix.plain
        digest = plain[3:] if plain.startswith(" · ") else (plain or None)
        append_agent_session_fold_heading(
            text,
            _QUESTIONS_TITLE,
            section_id=QUESTIONS_SECTION_ID,
            level=fold_level,
            summary=digest,
        )
        return
    heading = Text(_QUESTIONS_TITLE, style=_COLOR_HEADER)
    heading.append_text(suffix)
    append_section_heading(text, heading, section_id=QUESTIONS_SECTION_ID)


__all__ = [
    "QUESTIONS_SECTION_ID",
    "append_agent_questions_section",
]
