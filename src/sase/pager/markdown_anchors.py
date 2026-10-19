"""Pure Markdown anchor index for pager same-document links.

No Textual or Rich imports and no I/O. Text in, lines out.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

__all__ = ["MarkdownAnchorIndex", "build_markdown_anchor_index"]


_ATX_PREFIX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_TRAILING_ATTR_RE = re.compile(r"\{#([^}]+)\}$")
_CLOSING_HASH_RE = re.compile(r"[ \t]+#+[ \t]*$")
_HTML_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ANCHOR_NAME_RE = re.compile(
    r"""<a\b[^>]*\bname\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_BLOCK_ID_RE = re.compile(r"(?:^|\s)\^([A-Za-z0-9-]+)\s*$")
_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_BACKTICK_RE = re.compile(r"`+")


@dataclass
class MarkdownAnchorIndex:
    """Map of anchor keys to 1-based line numbers."""

    _exact: dict[str, int] = field(default_factory=dict)
    _lower: dict[str, int] = field(default_factory=dict)
    _loose: dict[str, int] = field(default_factory=dict)

    def line_for(self, fragment: str) -> int | None:
        """Return the 1-based line for *fragment*, or ``None``."""
        decoded = unquote(fragment or "")
        if decoded == "":
            return 1
        if decoded in self._exact:
            return self._exact[decoded]
        low = decoded.lower()
        if low in self._lower:
            return self._lower[low]
        loose = _loose_key(decoded)
        if loose and loose in self._loose:
            return self._loose[loose]
        if decoded == "top" and "top" not in self._exact:
            return 1
        return None


def build_markdown_anchor_index(text: str) -> MarkdownAnchorIndex:
    """Build an anchor index for *text*."""
    lines = _split_logical_lines(text)
    total = len(lines)
    frontmatter_skip: set[int] = set()
    if total and lines[0].strip() == "---":
        end = None
        for j in range(1, total):
            if lines[j].strip() in ("---", "..."):
                end = j
                break
        if end is None:
            frontmatter_skip = set(range(total))
        else:
            frontmatter_skip = set(range(end + 1))

    exact: dict[str, int] = {}

    def _register(key: str, line_no: int) -> None:
        if not key:
            return
        if key not in exact:
            exact[key] = line_no

    def _register_unique(base: str, line_no: int) -> None:
        if not base:
            return
        if base not in exact:
            exact[base] = line_no
            return
        counter = 1
        while True:
            candidate = f"{base}-{counter}"
            if candidate not in exact:
                exact[candidate] = line_no
                return
            counter += 1

    in_fence_char: str | None = None
    in_fence_len = 0
    underline_skip: set[int] = set()

    for i, line in enumerate(lines):
        line_no = i + 1
        if i in frontmatter_skip:
            continue
        bq = _strip_blockquote(line)
        fence = _parse_fence(bq)
        if in_fence_char is not None:
            if (
                fence is not None
                and fence[0] == in_fence_char
                and fence[1] >= in_fence_len
                and fence[2].strip() == ""
            ):
                in_fence_char = None
                in_fence_len = 0
            continue
        if fence is not None:
            in_fence_char = fence[0]
            in_fence_len = fence[1]
            continue
        if i in underline_skip:
            continue

        atx = _ATX_PREFIX_RE.match(bq)
        if atx is not None:
            raw = atx.group(2).strip()
            attr_id: str | None = None
            attr_match = _TRAILING_ATTR_RE.search(raw)
            if attr_match is not None:
                attr_id = attr_match.group(1).strip()
                raw = raw[: attr_match.start()].rstrip()
            raw = _CLOSING_HASH_RE.sub("", raw).strip()
            if attr_id:
                _register(attr_id, line_no)
            base = _github_slug(_clean_heading_text(raw))
            if base and base != attr_id:
                _register_unique(base, line_no)
            _register_line_extras(line, line_no, _register)
            continue

        # Setext: non-blank paragraph line followed by =/- underline.
        if bq.strip():
            nxt = i + 1
            if nxt < total and nxt not in frontmatter_skip:
                next_bq = _strip_blockquote(lines[nxt])
                # A fence delimiter is never a setext underline.
                next_fence = _parse_fence(next_bq)
                underline_motion = _SETEXT_UNDERLINE_RE.match(next_bq)
                if underline_motion is not None and next_fence is None:
                    para = bq.strip()
                    attr_id = None
                    attr_match = _TRAILING_ATTR_RE.search(para)
                    if attr_match is not None:
                        attr_id = attr_match.group(1).strip()
                        para = para[: attr_match.start()].rstrip()
                    para = _CLOSING_HASH_RE.sub("", para).strip()
                    if attr_id:
                        _register(attr_id, line_no)
                    base = _github_slug(_clean_heading_text(para))
                    if base and base != attr_id:
                        _register_unique(base, line_no)
                    _register_line_extras(line, line_no, _register)
                    underline_skip.add(nxt)
                    continue

        _register_line_extras(line, line_no, _register)

    lower: dict[str, int] = {}
    for key, value in exact.items():
        lowered = key.lower()
        if lowered not in lower:
            lower[lowered] = value
    loose: dict[str, int] = {}
    for key, value in exact.items():
        lk = _loose_key(key)
        if lk and lk not in loose:
            loose[lk] = value
    return MarkdownAnchorIndex(_exact=exact, _lower=lower, _loose=loose)


def _split_logical_lines(text: str) -> list[str]:
    if text == "":
        return []
    parts = text.split("\n")
    if text.endswith("\n"):
        parts.pop()
    cleaned: list[str] = []
    for part in parts:
        if part.endswith("\r"):
            part = part[:-1]
        cleaned.append(part)
    return cleaned


def _strip_blockquote(line: str) -> str:
    current = line
    while True:
        temp = current.lstrip(" ")
        if not temp.startswith(">"):
            return current
        after = temp[1:]
        if after.startswith((" ", "\t")):
            after = after[1:]
        current = after


def _parse_fence(line: str) -> tuple[str, int, str] | None:
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    # Tabs before a fence count as indented code, not a fence.
    if line.startswith("\t") or indent > 3:
        return None
    if stripped.startswith("```") or stripped.startswith("~~~"):
        char = stripped[0]
        count = 0
        while count < len(stripped) and stripped[count] == char:
            count += 1
        if count >= 3:
            return (char, count, stripped[count:])
    return None


def _register_line_extras(
    line: str, line_no: int, register: Callable[[str, int], None]
) -> None:
    for match in _HTML_ID_RE.finditer(line):
        value = match.group(1).strip()
        if value:
            register(value, line_no)
    for match in _ANCHOR_NAME_RE.finditer(line):
        value = match.group(1).strip()
        if value:
            register(value, line_no)
    block = _BLOCK_ID_RE.search(line)
    if block is not None:
        register("^" + block.group(1), line_no)


def _clean_heading_text(text: str) -> str:
    cleaned = _IMAGE_LINK_RE.sub(r"\1", text)
    cleaned = _INLINE_LINK_RE.sub(r"\1", cleaned)
    cleaned = _BACKTICK_RE.sub("", cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"[*~]", "", cleaned)
    cleaned = _strip_underscore_emphasis(cleaned)
    return cleaned


def _strip_underscore_emphasis(text: str) -> str:
    output: list[str] = []
    length = len(text)
    for pos, char in enumerate(text):
        if char != "_":
            output.append(char)
            continue
        prev_alnum = pos > 0 and text[pos - 1].isalnum()
        next_alnum = pos + 1 < length and text[pos + 1].isalnum()
        if prev_alnum and next_alnum:
            output.append(char)
    return "".join(output)


def _github_slug(text: str) -> str:
    lowered = text.lower()
    kept: list[str] = []
    for char in lowered:
        if char in ("-", "_", " "):
            kept.append(char)
            continue
        if unicodedata.category(char)[0] in ("L", "N", "M"):
            kept.append(char)
    return "".join(kept).replace(" ", "-")


def _loose_key(text: str) -> str:
    folded = text.casefold()
    output: list[str] = []
    prev_dash = False
    for char in folded:
        if char.isalnum():
            output.append(char)
            prev_dash = False
        else:
            if not prev_dash:
                output.append("-")
                prev_dash = True
    return "".join(output).strip("-")
