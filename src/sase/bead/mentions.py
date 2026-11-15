"""Textual-free bead-mention recognition for prompt text.

No I/O: a mention's presence and shape derive from the text and cursor
offset alone. Routing and store reads live in
``sase.ace.tui.models.bead_preview``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from sase.artifact_ref_operations import parse_artifact_ref, scan_artifact_refs
from sase.bead.cross_project import bead_id_prefix

BeadMentionForm = Literal["bare", "ref"]

_BARE_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
)
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*-[0-9a-z]{1,4}(?:\.\d+)*$")
_TRAILING_PUNCT = frozenset(".,;:!?)]}'\"`")
_BEFORE_REJECT = frozenset("/\\.+#%@[~-")
_AFTER_REJECT = frozenset("/\\-")
_UNQUALIFIED_BEAD_REF_RE = re.compile(
    r"(?<![\w@])bead:([A-Za-z0-9][A-Za-z0-9_.-]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _BeadMention:
    """One bead ID or ``@bead:``/``bead:`` ref covering a cursor offset."""

    bead_id: str
    start: int
    end: int
    form: BeadMentionForm
    prefix: str


def bead_mention_at(text: str, offset: int) -> _BeadMention | None:
    """Return the bead mention covering *offset*, or ``None``.

    *offset* is an absolute Python character offset. A cursor sitting on
    the first character of a token or just after its last character both
    count as covering the token.
    """
    if offset < 0 or offset > len(text):
        return None
    ref = _ref_mention_at(text, offset)
    if ref is not None:
        return ref
    return _bare_mention_at(text, offset)


def _ref_mention_at(text: str, offset: int) -> _BeadMention | None:
    for candidate in scan_artifact_refs(text):
        if candidate.kind != "bead" or not candidate.well_formed:
            continue
        start = candidate.candidate_span.start
        end = candidate.candidate_span.end
        if not _covers_offset(start, end, offset):
            continue
        mention = _mention_from_parsed_ref(
            candidate.reference,
            start=start,
            end=end,
        )
        if mention is not None:
            return mention

    for match in _UNQUALIFIED_BEAD_REF_RE.finditer(text):
        raw_id = match.group(1)
        trimmed = raw_id.rstrip("".join(_TRAILING_PUNCT))
        if not trimmed:
            continue
        start = match.start()
        end = match.start(1) + len(trimmed)
        if not _covers_offset(start, end, offset):
            continue
        mention = _mention_from_parsed_ref(
            f"bead:{trimmed}",
            start=start,
            end=end,
        )
        if mention is not None:
            return mention
    return None


def _mention_from_parsed_ref(
    reference: str,
    *,
    start: int,
    end: int,
) -> _BeadMention | None:
    try:
        parsed = parse_artifact_ref(reference)
    except (ValueError, RuntimeError):
        return None
    if parsed.kind_type != "bead":
        return None
    bead_id = (parsed.payload.id or "").strip()
    if not bead_id:
        return None
    prefix = bead_id_prefix(bead_id)
    if prefix is None:
        return None
    return _BeadMention(
        bead_id=bead_id,
        start=start,
        end=end,
        form="ref",
        prefix=prefix,
    )


def _bare_mention_at(text: str, offset: int) -> _BeadMention | None:
    index = _token_index(text, offset, _BARE_TOKEN_CHARS)
    if index is None:
        return None
    start, end = _grow_run(text, index, _BARE_TOKEN_CHARS)
    token = text[start:end]
    trimmed = token.rstrip("".join(_TRAILING_PUNCT))
    if not trimmed:
        return None
    end = start + len(trimmed)
    if "--" in trimmed or trimmed.endswith("-"):
        return None
    if _BARE_ID_RE.fullmatch(trimmed) is None:
        return None
    if not _bare_boundaries_ok(text, start, end):
        return None
    prefix = bead_id_prefix(trimmed)
    if prefix is None:
        return None
    return _BeadMention(
        bead_id=trimmed,
        start=start,
        end=end,
        form="bare",
        prefix=prefix,
    )


def _bare_boundaries_ok(text: str, start: int, end: int) -> bool:
    if start > 0:
        before = text[start - 1]
        if before in _BEFORE_REJECT or _is_word_char(before):
            return False
    if end < len(text):
        after = text[end]
        if after in _AFTER_REJECT or _is_word_char(after):
            return False
        if after == "." and end + 1 < len(text):
            nxt = text[end + 1]
            if _is_word_char(nxt) and not nxt.isdigit():
                return False
    return True


def _token_index(text: str, offset: int, charset: frozenset[str]) -> int | None:
    if offset < len(text) and text[offset] in charset:
        return offset
    if offset > 0 and text[offset - 1] in charset:
        return offset - 1
    return None


def _grow_run(text: str, index: int, charset: frozenset[str]) -> tuple[int, int]:
    start = index
    while start > 0 and text[start - 1] in charset:
        start -= 1
    end = index + 1
    while end < len(text) and text[end] in charset:
        end += 1
    return start, end


def _covers_offset(start: int, end: int, offset: int) -> bool:
    return start <= offset <= end


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


__all__ = ["bead_mention_at"]
