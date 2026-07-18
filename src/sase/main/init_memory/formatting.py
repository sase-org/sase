"""Markdown formatting for generated memory files."""

from __future__ import annotations

import re
import textwrap

_MARKDOWN_WRAP_WIDTH = 120
_FENCE_MARKERS = ("```", "~~~")
_STANDALONE_STRONG_LABEL_RE = re.compile(r"^\*\*[^*].*?\*\*[ \t]*$")
_INLINE_CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
_CODE_SPAN_SPACE_SENTINEL = "\x00"


def _is_fence_line(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(marker) for marker in _FENCE_MARKERS)


def _is_heading(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#")


def _is_list_item(line: str) -> bool:
    return line.startswith("- ")


def _is_standalone_strong_label(line: str) -> bool:
    return _STANDALONE_STRONG_LABEL_RE.match(line) is not None


def _wrap_text(
    text: str, *, initial_indent: str = "", subsequent_indent: str = ""
) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    # Prettier never breaks inside an inline code span, so wrap each span as a
    # single token to keep generated output a prettier fixpoint.
    protected = _INLINE_CODE_SPAN_RE.sub(
        lambda match: match.group(0).replace(" ", _CODE_SPAN_SPACE_SENTINEL),
        normalized,
    )
    wrapper = textwrap.TextWrapper(
        width=_MARKDOWN_WRAP_WIDTH,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return [
        line.replace(_CODE_SPAN_SPACE_SENTINEL, " ") for line in wrapper.wrap(protected)
    ]


def _starts_block(line: str) -> bool:
    return (
        _is_heading(line)
        or _is_fence_line(line)
        or _is_list_item(line)
        or _is_standalone_strong_label(line)
    )


def _standalone_strong_label_needs_hard_break(
    source_lines: list[str], index: int
) -> bool:
    next_index = index + 1
    if next_index >= len(source_lines):
        return False
    next_line = source_lines[next_index].rstrip()
    return bool(next_line.strip()) and not _starts_block(next_line)


def format_generated_memory_markdown(content: str) -> str:
    """Format generated memory Markdown without invoking external tools."""
    source_lines = content.splitlines()
    formatted: list[str] = []
    index = 0

    while index < len(source_lines):
        raw_line = source_lines[index]
        line = raw_line.rstrip()

        if not line.strip():
            if formatted and formatted[-1] != "":
                formatted.append("")
            index += 1
            continue

        if _is_fence_line(line):
            marker = line.lstrip()[:3]
            formatted.append(line)
            index += 1
            while index < len(source_lines):
                fenced_line = source_lines[index].rstrip()
                formatted.append(fenced_line)
                index += 1
                if fenced_line.lstrip().startswith(marker):
                    break
            continue

        if _is_heading(line):
            formatted.append(line)
            index += 1
            continue

        if _is_standalone_strong_label(raw_line):
            if _standalone_strong_label_needs_hard_break(source_lines, index):
                formatted.append(f"{line}  ")
            else:
                formatted.append(line)
            index += 1
            continue

        if _is_list_item(line):
            paragraph_parts = [line[2:].strip()]
            index += 1
            while index < len(source_lines):
                next_line = source_lines[index].rstrip()
                if not next_line.strip() or _starts_block(next_line):
                    break
                paragraph_parts.append(next_line.strip())
                index += 1
            formatted.extend(
                _wrap_text(
                    " ".join(paragraph_parts),
                    initial_indent="- ",
                    subsequent_indent="  ",
                )
            )
            continue

        paragraph_parts = [line.strip()]
        index += 1
        while index < len(source_lines):
            next_line = source_lines[index].rstrip()
            if not next_line.strip() or _starts_block(next_line):
                break
            paragraph_parts.append(next_line.strip())
            index += 1
        formatted.extend(_wrap_text(" ".join(paragraph_parts)))

    while formatted and formatted[-1] == "":
        formatted.pop()
    return "\n".join(formatted) + "\n"
