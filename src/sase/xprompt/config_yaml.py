"""YAML config xprompt insertion helpers.

Provides functions to generate and insert xprompt definitions into sase YAML
config files (sase.yml, default_config.yml, etc.) without reflowing unrelated
entries or comments. Sorted sections stay sorted; unsorted sections receive new
entries at the end.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from pathlib import Path
import tempfile

import yaml  # type: ignore[import-untyped]

from sase.xprompt.prompt_frontmatter import PromptFrontmatter

# Matches an xprompt entry key at exactly 2-space indent (e.g. "  foo:" or
# "  bd/next:").  The captured group is the entry name.
_ENTRY_RE = re.compile(r"^  ([\w/.:-]+):")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@dataclass(frozen=True, slots=True)
class _XpromptsSection:
    key_index: int
    start: int
    end: int
    is_empty_mapping: bool


@dataclass(frozen=True, slots=True)
class _EntryBlock:
    name: str
    start: int
    end: int


def generate_xprompt_yaml(
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
    *,
    frontmatter: PromptFrontmatter | None = None,
) -> list[str]:
    """Generate indented YAML lines for a single xprompt entry.

    Returns lines suitable for insertion under a ``xprompts:`` key (2-space
    indent for the entry name, 4-space for its properties).
    """
    if frontmatter is not None:
        return _generate_frontmatter_xprompt_yaml(name, frontmatter, content)

    content = content.rstrip("\n")

    if not inputs:
        # Short-form:  name: |-
        result = [f"  {name}: |-"]
        for line in content.split("\n"):
            result.append(f"    {line}" if line.strip() else "")
        return result

    # Long-form with input block
    result = [f"  {name}:"]
    result.append("    input:")
    for arg_name, arg_type in inputs:
        result.append(f"      {arg_name}: {arg_type}")
    result.append("    content: |-")
    for line in content.split("\n"):
        result.append(f"      {line}" if line.strip() else "")
    return result


def _generate_frontmatter_xprompt_yaml(
    name: str,
    frontmatter: PromptFrontmatter,
    content: str,
) -> list[str]:
    """Generate a config entry from the full prompt frontmatter field set."""
    mapping = frontmatter.to_mapping()
    mapping.pop("name", None)
    content = content.rstrip("\n")

    if not mapping:
        result = [f"  {name}: |-"]
        for line in content.split("\n"):
            result.append(f"    {line}" if line.strip() else "")
        return result

    result = [f"  {name}:"]
    dumped = yaml.safe_dump(
        mapping,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    if dumped:
        result.extend(f"    {line}" if line else "" for line in dumped.split("\n"))

    if content:
        result.append("    content: |-")
        for line in content.split("\n"):
            result.append(f"      {line}" if line.strip() else "")
    else:
        result.append('    content: ""')
    return result


def _is_top_level_key_line(line: str) -> bool:
    return bool(line) and not line[0].isspace() and not line.startswith("#")


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip())


def _find_xprompts_section(lines: list[str]) -> _XpromptsSection | None:
    """Return the xprompts section span, if present."""
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped not in {"xprompts:", "xprompts: {}"}:
            continue

        section_start = i + 1
        section_end = len(lines)
        for j in range(section_start, len(lines)):
            if _is_top_level_key_line(lines[j]):
                section_end = j
                break

        return _XpromptsSection(
            key_index=i,
            start=section_start,
            end=section_end,
            is_empty_mapping=stripped == "xprompts: {}",
        )

    return None


def _parse_entry_blocks(
    lines: list[str],
    section_start: int,
    section_end: int,
) -> list[_EntryBlock]:
    """Parse xprompt entry spans without absorbing surrounding scaffolding."""
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
            if line.strip() and _indent_width(line) <= 2:
                break
            i += 1

        block_end = i
        while block_end > block_start + 1 and not lines[block_end - 1].strip():
            block_end -= 1

        blocks.append(_EntryBlock(match.group(1), block_start, block_end))

    return blocks


def config_entry_line_span(path: Path | str, name: str) -> tuple[int, int] | None:
    """Return the 1-based inclusive line span for one config xprompt entry."""
    source = Path(path).expanduser()
    try:
        text = source.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        return None

    lines = text.splitlines()
    section = _find_xprompts_section(lines)
    if section is None:
        return None

    candidates = (name, name.rsplit("/", 1)[-1])
    for candidate in dict.fromkeys(candidates):
        matches = [
            block
            for block in _parse_entry_blocks(lines, section.start, section.end)
            if block.name == candidate
        ]
        if len(matches) == 1:
            block = matches[0]
            return block.start + 1, block.end
        if matches:
            return None
    return None


def _entry_sort_key(name: str) -> str:
    return f"{name}:"


def _is_sorted_by_entry_key(blocks: list[_EntryBlock]) -> bool:
    keys = [_entry_sort_key(block.name) for block in blocks]
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
    if not _is_sorted_by_entry_key(blocks):
        return None

    new_key = _entry_sort_key(name)
    for i, block in enumerate(blocks):
        if _entry_sort_key(block.name) > new_key:
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


def insert_xprompt_into_config(
    config_path: str,
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
    *,
    frontmatter: PromptFrontmatter | None = None,
) -> bool:
    """Insert an xprompt definition into a YAML config file.

    Existing entries, comments, and blank-line scaffolding are preserved
    byte-for-byte except for the one entry being inserted or overwritten. New
    entries are inserted in sorted position only when the existing section is
    already sorted by whole entry key (``name:``); otherwise, they are appended
    to the end of the section.

    Returns ``True`` on success, ``False`` on failure.
    """
    path = Path(config_path)

    if path.exists():
        file_text = path.read_text(encoding="utf-8")
    else:
        file_text = ""

    lines = file_text.split("\n")

    entry_lines = generate_xprompt_yaml(
        name,
        inputs,
        content,
        frontmatter=frontmatter,
    )

    section = _find_xprompts_section(lines)
    if section is None:
        # No xprompts section - append one at the end of the file.
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines:
            lines.append("")
        lines.append("xprompts:")
        lines.extend(entry_lines)
        lines.append("")
        _atomic_write_text(path, "\n".join(lines))
        return True

    # Replace ``xprompts: {}`` with bare ``xprompts:``
    if section.is_empty_mapping:
        lines[section.key_index] = "xprompts:"

    blocks = _parse_entry_blocks(lines, section.start, section.end)
    for block in blocks:
        if block.name == name:
            result = lines[: block.start] + entry_lines + lines[block.end :]
            _atomic_write_text(path, "\n".join(result))
            return True

    insert_before_block = _insert_index_for_new_entry(name, blocks)
    result = _insert_entry_lines(
        lines,
        section.start,
        blocks,
        insert_before_block,
        entry_lines,
    )

    _atomic_write_text(path, "\n".join(result))
    return True


__all__ = [
    "config_entry_line_span",
    "generate_xprompt_yaml",
    "insert_xprompt_into_config",
]
