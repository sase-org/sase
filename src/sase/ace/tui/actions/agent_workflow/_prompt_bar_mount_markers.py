"""Editor-review marker helpers for the agent prompt input bar."""

from __future__ import annotations

_EDITOR_REVIEW_MARKER = " @"


def strip_editor_review_markers(prompt: str) -> tuple[bool, str]:
    """Strip trailing `` @`` editor-review markers from returned editor text.

    Scans every line of *prompt*; a line matches when the text before its line
    terminator ends with the exact two-character suffix `` @`` (space then
    ``@``). Strips exactly those two characters from each matching line,
    preserving all other characters, every non-matching line, line order, and
    newline style (including the final newline).

    Returns ``(True, cleaned_text)`` when at least one line matched, otherwise
    ``(False, prompt)`` unchanged.

    This is an editor-return syntax, not a runtime directive: typing `` @`` in
    the prompt bar and submitting it is unaffected. The strip runs before
    macro-markdown loading so a marked separator such as ``--- @`` becomes a
    real ``---`` separator before stack parsing.
    """
    if _EDITOR_REVIEW_MARKER not in prompt:
        return False, prompt

    matched = False
    cleaned_lines: list[str] = []
    for line in prompt.splitlines(keepends=True):
        if line.endswith("\r\n"):
            content, terminator = line[:-2], "\r\n"
        elif line.endswith(("\n", "\r")):
            content, terminator = line[:-1], line[-1]
        else:
            content, terminator = line, ""
        if content.endswith(_EDITOR_REVIEW_MARKER):
            content = content[: -len(_EDITOR_REVIEW_MARKER)]
            matched = True
        cleaned_lines.append(content + terminator)

    if not matched:
        return False, prompt
    return True, "".join(cleaned_lines)
