"""Pure helpers for paired deletion of Jinja variable delimiters.

These planners give the Textual ``PromptTextArea`` the deletion counterpart to
the Jinja insertion special-casing in
:mod:`sase.ace.tui.widgets._prompt_text_area_key_pairing`. When the user
deletes one of the delimiter characters of a ``{{ ... }}`` variable tag, the
symmetric character on the other side is removed too, so the auto-generated
``{{  }}`` pair stays reversible:

- deleting the first opening ``{`` removes the last closing ``}``;
- deleting the second opening ``{`` removes the first closing ``}``;
- deleting either boundary padding space removes the other boundary space, so
  ``{{  }}`` collapses to ``{{}}`` and ``{{ name }}`` collapses to ``{{name}}``.

Like the generic pair planners in
:mod:`sase.ace.tui.widgets._paired_text_editing`, every planner takes the
*current* document ``text`` plus an absolute cursor ``offset`` and returns a
single contiguous :class:`TextEdit` describing the replacement to apply, or
``None`` when the edit does not apply. Callers translate the offsets back to
``(row, col)`` document locations before mutating the widget and are responsible
for skipping these planners while a selection is active. The planners only scan
fixed delimiter tokens over the in-memory text -- no Jinja parse, no I/O, no
event-loop work on the keypress path.
"""

from __future__ import annotations

from sase.ace.tui.widgets._paired_text_editing import TextEdit


def plan_jinja_delete_left(text: str, offset: int) -> TextEdit | None:
    """Plan a Backspace that removes a Jinja delimiter and its mirror partner.

    Backspace deletes the character at ``offset - 1``. When that character is a
    ``{{`` delimiter brace or a boundary padding space of a well-formed
    ``{{ ... }}`` tag, the symmetric character on the closing side is removed as
    well. Returns ``None`` (so the caller falls back to a single-character
    delete) for any other character or a malformed/unclosed tag.
    """
    return _plan_jinja_delete(text, offset, target=offset - 1)


def plan_jinja_delete_right(text: str, offset: int) -> TextEdit | None:
    """Plan a forward Delete that removes a Jinja delimiter and its mirror partner.

    Forward Delete removes the character at ``offset``. When that character is a
    ``{{`` delimiter brace or a boundary padding space of a well-formed
    ``{{ ... }}`` tag, the symmetric character on the closing side is removed as
    well. Returns ``None`` for any other character or a malformed/unclosed tag.
    """
    return _plan_jinja_delete(text, offset, target=offset)


def _plan_jinja_delete(text: str, offset: int, target: int) -> TextEdit | None:
    """Plan removing ``target`` and its Jinja mirror character as one edit.

    ``offset`` is the cursor position the caller started from; ``target`` is the
    character Textual would delete (``offset - 1`` for Backspace, ``offset`` for
    Delete). Returns a single contiguous :class:`TextEdit` that replaces the span
    from the earlier removed character through the later one with the original
    inner substring (i.e. both characters dropped), or ``None`` when ``target``
    is not a paired Jinja delimiter character.
    """
    if target < 0 or target >= len(text):
        return None
    pair = _paired_jinja_deletion(text, target)
    if pair is None:
        return None
    first, second = pair
    new_text = text[first + 1 : second]
    # Each removed character that sits strictly left of the cursor shifts it one
    # column left; characters at or right of the cursor leave it where it is.
    shift = (1 if first < offset else 0) + (1 if second < offset else 0)
    return TextEdit(
        start=first,
        end=second + 1,
        text=new_text,
        cursor=offset - shift,
    )


def _paired_jinja_deletion(text: str, target: int) -> tuple[int, int] | None:
    """Return the sorted ``(first, second)`` positions to remove for ``target``.

    Dispatches on the character under deletion: a ``{`` is matched as a ``{{``
    opener brace, a space is matched as a ``{{ ... }}`` boundary padding space.
    Returns ``None`` for any other character or when no valid mirror exists.
    """
    char = text[target]
    if char == "{":
        return _paired_delimiter_deletion(text, target)
    if char == " ":
        return _paired_padding_deletion(text, target)
    return None


def _paired_delimiter_deletion(text: str, target: int) -> tuple[int, int] | None:
    """Pair a ``{{`` opener brace at ``target`` with its mirror ``}}`` brace.

    By delimiter symmetry the first opening ``{`` maps to the last closing ``}``
    and the second opening ``{`` maps to the first closing ``}``. Returns the
    sorted positions of the two characters to remove, or ``None`` when ``target``
    is not part of a ``{{`` opener that has a following ``}}`` closer.
    """
    if target + 1 < len(text) and text[target + 1] == "{":
        open_start = target
        target_is_first_brace = True
    elif target - 1 >= 0 and text[target - 1] == "{":
        open_start = target - 1
        target_is_first_brace = False
    else:
        return None
    close_start = _find_jinja_close(text, open_start)
    if close_start is None:
        return None
    if target_is_first_brace:
        # First opening ``{`` (open_start) mirrors the last closing ``}``.
        return open_start, close_start + 1
    # Second opening ``{`` (open_start + 1) mirrors the first closing ``}``.
    return open_start + 1, close_start


def _paired_padding_deletion(text: str, target: int) -> tuple[int, int] | None:
    """Pair the two boundary padding spaces of a well-formed ``{{ ... }}`` tag.

    The left boundary space sits at ``open_start + 2`` (just after ``{{``) and
    the right boundary space at ``close_start - 1`` (just before ``}}``). When
    ``target`` is one of those two distinct spaces and both are spaces, returns
    their sorted positions so deleting either collapses both. Interior spaces and
    single-space tags such as ``{{ }}`` return ``None``.
    """
    span = _enclosing_jinja_var_span(text, target)
    if span is None:
        return None
    open_start, close_start = span
    left = open_start + 2
    right = close_start - 1
    if left >= right:
        return None
    if target not in (left, right):
        return None
    if text[left] != " " or text[right] != " ":
        return None
    return left, right


def _find_jinja_close(text: str, open_start: int) -> int | None:
    """Return the start index of the nearest ``}}`` following a ``{{`` opener.

    Searches for the closing delimiter beginning just past the opener's two
    braces. Returns ``None`` when no ``}}`` follows.
    """
    index = text.find("}}", open_start + 2)
    return None if index == -1 else index


def _enclosing_jinja_var_span(text: str, target: int) -> tuple[int, int] | None:
    """Return ``(open_start, close_start)`` of the ``{{ ... }}`` tag around ``target``.

    ``open_start`` is the index of the nearest ``{{`` before ``target`` and
    ``close_start`` the index of the nearest ``}}`` at or after it. The candidate
    span must be a clean variable tag: its inner content may not contain another
    ``{{`` or ``}}`` delimiter. Returns ``None`` when ``target`` is not enclosed
    by such a tag.
    """
    open_start = text.rfind("{{", 0, target)
    if open_start == -1:
        return None
    close_start = text.find("}}", target)
    if close_start == -1:
        return None
    inner = text[open_start + 2 : close_start]
    if "{{" in inner or "}}" in inner:
        return None
    return open_start, close_start
