"""Minimal-edit YAML writer for ``ace.snippets`` entries.

Inserts or replaces a single snippet under the nested ``ace: -> snippets:``
mapping of a sase YAML config file without reflowing unrelated entries or
comments. Snippet values are emitted as strip-chomped block scalars
(``name: |-``) so the writer's trailing-newline stripping survives the round
trip. Sorted sections stay sorted; unsorted sections receive new entries at the
end.

Patterned after :mod:`sase.xprompt.config_yaml` (the flat ``xprompts:`` writer)
but nested one mapping level deeper.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

# Matches a snippet entry key at exactly 4-space indent (``    foo:`` or
# ``    foo/bar:``).  The captured group is the entry name.
_ENTRY_RE = re.compile(r"^    ([\w/.:-]+):")


@dataclass(frozen=True, slots=True)
class _Section:
    key_index: int
    start: int
    end: int
    is_empty_mapping: bool


@dataclass(frozen=True, slots=True)
class _EntryBlock:
    name: str
    start: int
    end: int


def generate_snippet_yaml(name: str, template: str) -> list[str]:
    """Generate YAML lines for one snippet entry.

    Returns lines for insertion under ``ace: -> snippets:`` (4-space indent for
    the entry name, 6-space for the block-scalar body).
    """
    template = template.rstrip("\n")
    result = [f"    {name}: |-"]
    for line in template.split("\n"):
        result.append(f"      {line}" if line.strip() else "")
    return result


def _is_top_level_key_line(line: str) -> bool:
    return bool(line) and not line[0].isspace() and not line.startswith("#")


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip())


def _find_top_level_section(lines: list[str], key: str) -> _Section | None:
    """Return the span of top-level mapping ``key:``, if present."""
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped not in {f"{key}:", f"{key}: {{}}"}:
            continue

        section_start = i + 1
        section_end = len(lines)
        for j in range(section_start, len(lines)):
            if _is_top_level_key_line(lines[j]):
                section_end = j
                break

        return _Section(
            key_index=i,
            start=section_start,
            end=section_end,
            is_empty_mapping=stripped == f"{key}: {{}}",
        )

    return None


def _find_snippets_subsection(
    lines: list[str],
    ace_start: int,
    ace_end: int,
) -> _Section | None:
    """Return the ``snippets:`` subsection span within the ``ace:`` section."""
    for i in range(ace_start, ace_end):
        line = lines[i]
        if _indent_width(line) != 2:
            continue
        stripped = line.rstrip()
        if stripped not in {"  snippets:", "  snippets: {}"}:
            continue

        sub_start = i + 1
        sub_end = ace_end
        for j in range(sub_start, ace_end):
            if lines[j].strip() and _indent_width(lines[j]) <= 2:
                sub_end = j
                break

        return _Section(
            key_index=i,
            start=sub_start,
            end=sub_end,
            is_empty_mapping=stripped == "  snippets: {}",
        )

    return None


def _parse_entry_blocks(
    lines: list[str],
    section_start: int,
    section_end: int,
) -> list[_EntryBlock]:
    """Parse snippet entry spans without absorbing surrounding scaffolding."""
    blocks: list[_EntryBlock] = []
    i = section_start
    while i < section_end:
        match = _ENTRY_RE.match(lines[i])
        if match is None:
            i += 1
            continue

        block_start = i
        i += 1
        while i < section_end:
            line = lines[i]
            if line.strip() and _indent_width(line) <= 4:
                break
            i += 1

        block_end = i
        while block_end > block_start + 1 and not lines[block_end - 1].strip():
            block_end -= 1

        blocks.append(_EntryBlock(match.group(1), block_start, block_end))

    return blocks


def _snippet_sort_key(name: str) -> str:
    """Sort key for a snippet entry: the trigger name itself.

    Unlike the xprompt writer (which tie-breaks on a trailing ``:``), snippet
    triggers are validated as ``[A-Za-z0-9_]+`` and are expected to sort by the
    plain trigger name, so ``foo`` sorts before ``foo1``.
    """
    return name


def _is_sorted_by_snippet_name(blocks: list[_EntryBlock]) -> bool:
    keys = [_snippet_sort_key(block.name) for block in blocks]
    return keys == sorted(keys)


def _canonical_gap(blocks: list[_EntryBlock], lines: list[str]) -> int:
    """Return the representative blank-line count between adjacent entries."""
    gaps: list[int] = []
    for previous, current in zip(blocks, blocks[1:], strict=False):
        gap_lines = lines[previous.end : current.start]
        if all(not line.strip() for line in gap_lines):
            gaps.append(len(gap_lines))

    if not gaps:
        return 0

    best_gap = gaps[0]
    best_count = gaps.count(best_gap)
    for gap in gaps[1:]:
        count = gaps.count(gap)
        if count > best_count:
            best_gap = gap
            best_count = count
    return best_gap


def _insert_index_for_new_entry(
    name: str,
    blocks: list[_EntryBlock],
) -> int | None:
    """Return the block index to insert before, or None to append."""
    if not _is_sorted_by_snippet_name(blocks):
        return None

    new_key = _snippet_sort_key(name)
    for i, block in enumerate(blocks):
        if _snippet_sort_key(block.name) > new_key:
            return i
    return None


def _insert_entry_lines(
    lines: list[str],
    section_start: int,
    blocks: list[_EntryBlock],
    insert_before_block: int | None,
    entry_lines: list[str],
) -> list[str]:
    if not blocks:
        return lines[:section_start] + entry_lines + lines[section_start:]

    gap_lines = [""] * _canonical_gap(blocks, lines)
    if insert_before_block is None:
        insert_at = blocks[-1].end
        inserted = gap_lines + entry_lines
    else:
        insert_at = blocks[insert_before_block].start
        inserted = entry_lines + gap_lines

    return lines[:insert_at] + inserted + lines[insert_at:]


def _ace_content_insert_index(lines: list[str], start: int, end: int) -> int:
    """Return the index just after the last non-blank line in ``[start, end)``."""
    insert_at = start
    for i in range(start, end):
        if lines[i].strip():
            insert_at = i + 1
    return insert_at


def insert_snippet_into_config(
    config_path: str,
    name: str,
    template: str,
) -> bool:
    """Insert or replace a snippet under ``ace.snippets`` in a YAML config file.

    Existing entries, comments, and blank-line scaffolding are preserved except
    for the one snippet being inserted or overwritten. New entries are inserted
    in sorted position only when the existing section is already sorted by whole
    entry key (``name:``); otherwise, they are appended to the end of the
    section.  Missing ``ace:`` / ``snippets:`` mappings are created as needed,
    and an empty/missing file is treated as a valid starting point.

    Returns ``True`` on success.
    """
    path = Path(config_path)

    if path.exists():
        file_text = path.read_text(encoding="utf-8")
    else:
        file_text = ""

    lines = file_text.split("\n")
    entry_lines = generate_snippet_yaml(name, template)

    ace = _find_top_level_section(lines, "ace")
    if ace is None:
        # No ace section - append ``ace: -> snippets:`` at the end of the file.
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines:
            lines.append("")
        lines.append("ace:")
        lines.append("  snippets:")
        lines.extend(entry_lines)
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # Replace ``ace: {}`` with bare ``ace:``
    if ace.is_empty_mapping:
        lines[ace.key_index] = "ace:"

    snippets = _find_snippets_subsection(lines, ace.start, ace.end)
    if snippets is None:
        # No snippets subsection - add one at the end of the ace section content.
        insert_at = _ace_content_insert_index(lines, ace.start, ace.end)
        inserted = ["  snippets:"] + entry_lines
        result = lines[:insert_at] + inserted + lines[insert_at:]
        path.write_text("\n".join(result), encoding="utf-8")
        return True

    # Replace ``snippets: {}`` with bare ``snippets:``
    if snippets.is_empty_mapping:
        lines[snippets.key_index] = "  snippets:"

    blocks = _parse_entry_blocks(lines, snippets.start, snippets.end)
    for block in blocks:
        if block.name == name:
            result = lines[: block.start] + entry_lines + lines[block.end :]
            path.write_text("\n".join(result), encoding="utf-8")
            return True

    insert_before_block = _insert_index_for_new_entry(name, blocks)
    result = _insert_entry_lines(
        lines,
        snippets.start,
        blocks,
        insert_before_block,
        entry_lines,
    )

    path.write_text("\n".join(result), encoding="utf-8")
    return True


__all__ = [
    "generate_snippet_yaml",
    "insert_snippet_into_config",
]
