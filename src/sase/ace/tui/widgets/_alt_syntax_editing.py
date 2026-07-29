"""Pure helpers for ``%{...}`` alt-shorthand editing in the prompt input.

These functions plan in-memory text edits for the ``%{ ... | ... }`` alt
shorthand so the Textual ``PromptTextArea`` can pad fresh alt braces and
normalize ``|`` separators while keeping all logic off the event loop (no I/O,
bounded string scanning only). Paired deletion of the ``%{}`` braces is handled
by the generic helpers in :mod:`sase.ace.tui.widgets._paired_text_editing`.

Every planner takes the *current* document ``text`` plus an absolute cursor
``offset`` and returns a :class:`TextEdit` describing the replacement to apply,
or ``None`` when the edit does not apply. Callers translate the offsets back to
``(row, col)`` document locations before mutating the widget.
"""

from __future__ import annotations

from sase.ace.tui.widgets._paired_text_editing import TextEdit

# A ``%`` may open a ``%{`` directive at the start of the document or directly
# after whitespace, a directive-value colon, or one of these opening characters
# -- mirrors the directive-valid contexts used by ``_ALT_DIRECTIVE_RE``.
_DIRECTIVE_OPENING_CONTEXTS = frozenset(":([{\"'")
_PAIR_SAFE_CLOSE_CHARS = frozenset(")]}>")
# Trailing punctuation can never begin a token, so a padded ``%{  }`` inserted
# directly before it is unambiguous -- this is how a fan-out question is
# normally authored (``Which is better %{ A | B }?``).
_PAIR_SAFE_PUNCTUATION_CHARS = frozenset(".,;:!?")
_PAIR_SAFE_FOLLOW_CHARS = _PAIR_SAFE_CLOSE_CHARS | _PAIR_SAFE_PUNCTUATION_CHARS


def _is_directive_valid_brace_opening(text: str, percent_index: int) -> bool:
    """Return True when ``%`` at *percent_index* may open a ``%{`` directive."""
    if percent_index < 0 or percent_index >= len(text):
        return False
    if text[percent_index] != "%":
        return False
    if percent_index == 0:
        return True
    previous = text[percent_index - 1]
    return previous.isspace() or previous in _DIRECTIVE_OPENING_CONTEXTS


def _next_char_allows_alt_brace_pair(text: str, offset: int) -> bool:
    """Return True before whitespace, a safe closer, or trailing punctuation."""
    if offset >= len(text):
        return True
    following = text[offset]
    return following.isspace() or following in _PAIR_SAFE_FOLLOW_CHARS


def plan_alt_brace_pair(text: str, offset: int) -> TextEdit | None:
    """Plan padded brace insertion for a directive-valid ``%{`` opener.

    The typed ``{`` replaces nothing at *offset* and expands to ``"{  }"`` in the
    TUI, leaving the cursor after the first padding space. Returns ``None`` for
    ordinary ``{`` insertion contexts or unsafe following characters.
    """
    percent_index = offset - 1
    if not _is_directive_valid_brace_opening(text, percent_index):
        return None
    if not _next_char_allows_alt_brace_pair(text, offset):
        return None
    return TextEdit(start=offset, end=offset, text="{  }", cursor=offset + 2)


def plan_alt_separator(text: str, offset: int) -> TextEdit | None:
    """Plan a normalized ``|`` separator insertion inside a live ``%{...}``.

    Returns ``None`` when the cursor is not inside an active ``%{...}`` span.
    Otherwise the current branch (from the last top-level ``|`` or the opening
    ``{`` up to the cursor) has its comma spacing normalized and a padded
    ``" | "`` separator is appended, leaving the cursor after the trailing
    space and before the closing ``}``.
    """
    span = _find_enclosing_alt_span(text, offset)
    if span is None:
        return None
    content_start = span[0]
    branch_start = _current_branch_start(text, content_start, offset)
    before = text[branch_start:offset]
    replacement = _normalize_branch_text(before) + " | "
    return TextEdit(
        start=branch_start,
        end=offset,
        text=replacement,
        cursor=branch_start + len(replacement),
    )


def _find_enclosing_alt_span(text: str, offset: int) -> tuple[int, int] | None:
    """Return ``(content_start, content_end)`` of the ``%{...}`` enclosing *offset*.

    ``content_start`` is the index just after the opening ``{`` and
    ``content_end`` is the index of the matching ``}`` (or ``len(text)`` when the
    span is still unclosed). Returns ``None`` when *offset* is not inside any
    directive-valid ``%{...}`` span.
    """
    search_from = 0
    while True:
        index = text.find("%{", search_from)
        if index == -1:
            return None
        if _is_directive_valid_brace_opening(text, index):
            content_start = index + 2
            close = _find_matching_brace(text, index + 1)
            content_end = len(text) if close is None else close
            if content_start <= offset <= content_end:
                return content_start, content_end
        search_from = index + 2


def _find_matching_brace(text: str, open_index: int) -> int | None:
    """Return the index of the ``}`` matching the ``{`` at *open_index*.

    Tracks brace nesting and skips backtick-quoted text so nested ``{}`` and
    quoted braces do not terminate the span early. Returns ``None`` when no
    matching close brace exists.
    """
    depth = 0
    in_backtick = False
    for i in range(open_index, len(text)):
        char = text[i]
        if in_backtick:
            if char == "`":
                in_backtick = False
            continue
        if char == "`":
            in_backtick = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _current_branch_start(text: str, content_start: int, offset: int) -> int:
    """Return the start of the branch the cursor is editing within a span.

    The branch begins after the last top-level ``|`` before the cursor (or at
    ``content_start`` when there is none), skipping any leading whitespace so the
    space following a previous separator is preserved untouched.
    """
    pipe = _last_top_level_pipe(text, content_start, offset)
    start = content_start if pipe is None else pipe + 1
    while start < offset and text[start].isspace():
        start += 1
    return start


def _last_top_level_pipe(text: str, content_start: int, offset: int) -> int | None:
    """Return the index of the last top-level ``|`` in ``[content_start, offset)``.

    Pipes nested inside ``()``, ``[]``, ``{}`` or backticks are ignored so only
    branch separators count.
    """
    last: int | None = None
    paren = bracket = brace = 0
    in_backtick = False
    for i in range(content_start, offset):
        char = text[i]
        if in_backtick:
            if char == "`":
                in_backtick = False
            continue
        if char == "`":
            in_backtick = True
        elif char == "(":
            paren += 1
        elif char == ")":
            paren = max(0, paren - 1)
        elif char == "[":
            bracket += 1
        elif char == "]":
            bracket = max(0, bracket - 1)
        elif char == "{":
            brace += 1
        elif char == "}":
            brace = max(0, brace - 1)
        elif char == "|" and paren == bracket == brace == 0:
            last = i
    return last


def _normalize_branch_text(branch: str) -> str:
    """Normalize comma spacing within a single alt branch.

    Each ``,`` keeps exactly one trailing space and no leading space, and the
    branch is stripped of surrounding whitespace, so ``foo ,bar, and baz``
    becomes ``foo, bar, and baz``.
    """
    return ", ".join(part.strip() for part in branch.split(","))
