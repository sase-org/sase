"""Per-turn card blocks for the agent-session Reply card.

One loop serves hint and non-hint modes: the caller supplies a
``render_phase(phase, block_id)`` callback that builds one phase's divider
(carrying ``block_id`` anchor meta) plus content, and this module wraps each
phase's parts in a :class:`CardBlock` whose :class:`BlockMeta` matches the
JUMP roster facts by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from ...models.agent import Agent
from ..decks.card_block import BlockMeta, CardBlock, card_block_id
from ._agent_display_agent_session import AgentSessionTurnFacts
from ._agent_display_content import get_phase_label
from ._fold_language import fold_count_style
from ._helpers import (
    PROMPT_PANEL_SECTION_HEADING_STYLE,
    append_section_heading,
)


def session_reply_heading(phase_count: int) -> Text:
    """Return the ``AGENT REPLY · N`` heading without the vestigial rule prefix."""
    heading = Text()
    append_section_heading(heading, _reply_heading_text(phase_count))
    return heading


def _reply_heading_text(phase_count: int) -> Text:
    heading = Text(
        "AGENT REPLY",
        style=PROMPT_PANEL_SECTION_HEADING_STYLE,
    )
    heading.append(
        f" · {phase_count}",
        style=fold_count_style("AGENT REPLY"),
    )
    return heading


def block_meta_for_session_turn(facts: AgentSessionTurnFacts, number: int) -> BlockMeta:
    """Adapt one turn's roster facts into its card-block meta.

    ``number`` is the turn's chronological index, which is its JUMP roster
    number.
    """
    return BlockMeta(
        number=str(number),
        label=facts.label,
        glyph=facts.glyph,
        accent=facts.accent,
        status_bucket=facts.status_bucket,
        kind=facts.kind,
    )


def phase_card_block(
    phase: Agent,
    parts: Sequence[RenderableType],
    *,
    meta: BlockMeta,
) -> CardBlock:
    """Wrap one phase's parts in a stably identified card block.

    Callers adapt their per-phase facts through
    :func:`block_meta_for_session_turn`: session turns pass roster facts
    while the legacy ``followup_agents`` Reply path passes role-suffix facts.
    """
    return CardBlock(
        card_block_id(phase.identity),
        get_phase_label(phase),
        *parts,
        meta=meta,
    )


def build_session_reply_blocks(
    phases: Sequence[Agent],
    facts: Sequence[AgentSessionTurnFacts],
    *,
    render_phase: Callable[[Agent, str], list[Any]],
) -> tuple[Text, list[CardBlock]]:
    """Build the Reply heading plus one block per turn, in turn order."""
    heading = session_reply_heading(len(phases))
    blocks = [
        phase_card_block(
            phase,
            render_phase(phase, card_block_id(phase.identity)),
            meta=block_meta_for_session_turn(phase_facts, number),
        )
        for number, (phase, phase_facts) in enumerate(zip(phases, facts, strict=True))
    ]
    return heading, blocks


__all__ = [
    "block_meta_for_session_turn",
    "build_session_reply_blocks",
    "phase_card_block",
    "session_reply_heading",
]
