"""Pure-logic directive completion engine for the prompt input bar."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _KNOWN_DIRECTIVES

_DIRECTIVE_TOKEN_RE = re.compile(r"^%[A-Za-z0-9_]*$")
_DIRECTIVE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_]")
_DIRECTIVE_OPENING_CONTEXTS = frozenset("([{\"'")
_USER_FACING_DIRECTIVES = frozenset((*_KNOWN_DIRECTIVES, "alt"))


@dataclass(frozen=True, slots=True)
class DirectiveCompletionMetadata:
    """Display metadata for a prompt directive completion candidate."""

    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    description: str = ""


_DIRECTIVE_ARGUMENT_HINTS: dict[str, str] = {
    "alt": "(variants)",
    "approve": "flag",
    "edit": "flag",
    "epic": "flag",
    "hide": "flag",
    "model": ":model or (models)",
    "name": ":agent",
    "plan": "flag",
    "repeat": ":count",
    "group": ":tag",
    "wait": ":agent or :duration",
}


_DIRECTIVE_DESCRIPTIONS: dict[str, str] = {
    "alt": "split a prompt into text/model variants",
    "approve": "run autonomously without plan approval prompts",
    "edit": "return editor text to the prompt bar before launch",
    "epic": "plan first and auto-approve the plan as an epic",
    "hide": "hide the agent from the default Agents tab",
    "model": "choose one or more provider/model targets",
    "name": "assign, auto-generate, or force-reuse an agent name",
    "plan": "create a plan first, then wait for approval",
    "repeat": "run the prompt multiple serial iterations",
    "group": "assign a user-managed agent tag",
    "wait": "defer launch until agents complete or time elapses",
}


def is_directive_like_token(token: str) -> bool:
    """Return True when token looks like a prompt directive reference."""
    return _DIRECTIVE_TOKEN_RE.fullmatch(token) is not None


def extract_directive_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str] | None:
    """Extract a directive token around a cursor position in one line."""
    col = min(col, len(line))

    token_start = col
    while token_start > 0 and _is_directive_identifier(line[token_start - 1]):
        token_start -= 1

    percent_index = token_start - 1
    if percent_index < 0 or line[percent_index] != "%":
        return None
    if not _has_valid_directive_context(line, percent_index):
        return None

    token_end = col
    while token_end < len(line) and _is_directive_identifier(line[token_end]):
        token_end += 1

    token = line[percent_index:token_end]
    if not is_directive_like_token(token):
        return None
    return percent_index, token_end, token


def build_directive_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a directive token."""
    if not is_directive_like_token(token):
        return [], ""

    partial = token[1:]
    partial_lower = partial.lower()
    aliases_by_directive = _aliases_by_directive()
    candidates = [
        CompletionCandidate(
            display=f"%{directive}",
            insertion=f"%{directive}",
            is_dir=False,
            name=directive,
            metadata=DirectiveCompletionMetadata(
                aliases=aliases_by_directive.get(directive, ()),
                argument_hint=_DIRECTIVE_ARGUMENT_HINTS.get(directive, ""),
                description=_DIRECTIVE_DESCRIPTIONS.get(directive, ""),
            ),
        )
        for directive in sorted(_USER_FACING_DIRECTIVES)
        if _matches_directive(directive, aliases_by_directive, partial_lower)
    ]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion[1:] for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def _matches_directive(
    directive: str,
    aliases_by_directive: dict[str, tuple[str, ...]],
    partial_lower: str,
) -> bool:
    if directive.lower().startswith(partial_lower):
        return True
    return any(
        alias.startswith(partial_lower) for alias in aliases_by_directive[directive]
    )


def _aliases_by_directive() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {
        directive: [] for directive in _USER_FACING_DIRECTIVES
    }
    for alias, canonical in _DIRECTIVE_ALIASES.items():
        if canonical in grouped:
            grouped[canonical].append(alias)
    return {directive: tuple(sorted(aliases)) for directive, aliases in grouped.items()}


def _has_valid_directive_context(line: str, percent_index: int) -> bool:
    if percent_index == 0:
        return True
    previous = line[percent_index - 1]
    return previous.isspace() or previous in _DIRECTIVE_OPENING_CONTEXTS


def _is_directive_identifier(char: str) -> bool:
    return _DIRECTIVE_IDENTIFIER_RE.fullmatch(char) is not None
