"""Shared data models for prompt stack actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StashedPromptPane:
    """One captured prompt-bar pane handed to the app for persistence.

    The bar captures presentation-side state only (the stripped pane ``text``,
    the bar's shared YAML ``frontmatter``, and the pane's original
    ``pane_index``); the app layer enriches it with id / timestamp / project
    before writing through ``prompt_stash_facade`` (boundary rule D6).
    """

    text: str
    frontmatter: str = ""
    pane_index: int = 0


@dataclass(frozen=True)
class PromptGPrefixHintEntry:
    """One currently available prompt ``g`` prefix hint."""

    key: str
    label: str
    aliases: tuple[str, ...] = ()
