"""Completion-context helpers for profile-driven Patch queries."""

from __future__ import annotations

from sase.ace.query_profile import CompiledQueryProfile


def patch_completion_context(
    text: str,
    cursor: int,
    *,
    profile: CompiledQueryProfile,
) -> tuple[str, str, bool]:
    """Return ``(kind, prefix, negated)`` for the boolean Patch query grammar."""

    cursor = min(max(cursor, 0), len(text))
    before = text[:cursor]
    quoted_prefix = _quoted_prefix(before)
    if quoted_prefix is not None:
        return ("text", quoted_prefix, False)

    token_start = _token_start(before)
    token = before[token_start:]
    folded = token.casefold()
    negated = False
    if folded.startswith("!"):
        negated = True
        token = token[1:]
        folded = token.casefold()

    if not token:
        return ("key", "", negated)
    if folded in {"and", "or", "not"}:
        return ("key", "", False)
    if token == "%":
        return ("macro", "", False)
    if token.startswith("%"):
        return ("macro", token[1:].casefold(), False)
    sigil_fields = {item.sigil: item.field for item in profile.sigils}
    if token[0] in sigil_fields:
        return (sigil_fields[token[0]], token[1:], negated)
    if ":" in token:
        key, prefix = token.split(":", 1)
        return (key.casefold(), prefix, negated)
    return ("key", token, negated)


def _quoted_prefix(before: str) -> str | None:
    in_quotes = False
    start = 0
    index = 0
    while index < len(before):
        char = before[index]
        if char == '"' and not _is_escaped(before, index):
            in_quotes = not in_quotes
            start = index + 1
        index += 1
    if not in_quotes:
        return None
    return before[start:]


def _token_start(before: str) -> int:
    in_quotes = False
    start = 0
    for index, char in enumerate(before):
        if char == '"' and not _is_escaped(before, index):
            in_quotes = not in_quotes
        elif not in_quotes and (char.isspace() or char in "()"):
            start = index + 1
    return start


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 1


__all__ = ["patch_completion_context"]
