"""Memory note parsing, discovery, and rendering helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import re
import textwrap
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

from sase.markdown_width import markdown_print_width
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_read_root,
)

AGENTS_PARENT = "AGENTS.md"
DEFAULT_MEMORY_PRIORITY = 20
MEMORY_DIR = CANONICAL_MEMORY_RELATIVE_ROOT.as_posix()
README_FILENAME = "README.md"

MemoryNoteType = Literal["core", "reference"]
MemoryNoteTypeSource = Literal["frontmatter", "missing", "invalid"]
MemoryNoteParentSource = Literal["frontmatter", "missing", "invalid"]
MemoryNotePrioritySource = Literal["frontmatter", "missing", "invalid"]

_LEGACY_NOTE_TYPES = {"short": "core", "long": "reference"}
_VALID_NOTE_TYPES = frozenset({"core", "reference"})
_CANONICAL_FRONTMATTER_KEYS = frozenset({"type", "parent", "priority", "description"})
_RETIRED_FRONTMATTER_KEYS = frozenset({"keywords"})
_NON_EXTENSION_FRONTMATTER_KEYS = (
    _CANONICAL_FRONTMATTER_KEYS | _RETIRED_FRONTMATTER_KEYS
)
_YAML_WIDTH = 1_000_000


class _MemoryFrontmatterDumper(yaml.SafeDumper):
    """YAML dumper for canonical memory-note frontmatter."""


@dataclass(frozen=True)
class MemoryNote:
    """One markdown memory note rooted under a repository or home directory."""

    path: Path
    type: str | None
    parent: str
    description: str | None
    body: str
    frontmatter: Mapping[str, Any]
    type_source: MemoryNoteTypeSource
    parent_source: MemoryNoteParentSource
    source_path: Path | None = None
    priority: int = DEFAULT_MEMORY_PRIORITY
    priority_source: MemoryNotePrioritySource = "missing"

    @property
    def relative_path(self) -> str:
        """Return the root-relative note path in POSIX form."""
        return self.path.as_posix()

    @property
    def source_relative_path(self) -> Path:
        """Return the root-relative on-disk source used to read this note."""
        return self.source_path or self.path


@dataclass(frozen=True)
class GeneratedShortMemoryNote:
    """Metadata for a generated core memory note keyed by root-relative path."""

    body: str
    priority: int = DEFAULT_MEMORY_PRIORITY


@dataclass(frozen=True)
class GeneratedLongMemoryNote:
    """Metadata for a generated reference memory note keyed by root-relative path."""

    description: str
    parent: str = AGENTS_PARENT


@dataclass(frozen=True)
class _FrontmatterBlock:
    frontmatter: Mapping[str, Any]
    body: str
    had_frontmatter: bool


def _frontmatter_close_line_range(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None

    offset = len(lines[0])
    for line in lines[1:]:
        line_start = offset
        offset += len(line)
        if line.strip() == "---":
            return line_start, offset
    return None


def _parse_frontmatter_block(text: str) -> _FrontmatterBlock:
    close_range = _frontmatter_close_line_range(text)
    if close_range is None:
        return _FrontmatterBlock(frontmatter={}, body=text, had_frontmatter=False)

    close_start, close_end = close_range
    first_line_end = text.find("\n") + 1
    raw_frontmatter = text[first_line_end:close_start]
    body = text[close_end:]
    if body.startswith("\n"):
        body = body[1:]
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError:
        return _FrontmatterBlock(frontmatter={}, body=body, had_frontmatter=True)
    if not isinstance(loaded, dict):
        return _FrontmatterBlock(frontmatter={}, body=body, had_frontmatter=True)
    frontmatter = {key: value for key, value in loaded.items() if isinstance(key, str)}
    return _FrontmatterBlock(
        frontmatter=frontmatter,
        body=body,
        had_frontmatter=True,
    )


def _normalized_scalar(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _normalized_description(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized_lines = [" ".join(line.split()) for line in value.splitlines()]
    while normalized_lines and not normalized_lines[0]:
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    if not normalized_lines:
        return None

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in normalized_lines:
        if not line:
            if previous_blank:
                continue
            previous_blank = True
        else:
            previous_blank = False
        collapsed_lines.append(line)
    return "\n".join(collapsed_lines)


def _normalized_path_scalar(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("\\", "/")
    return normalized or None


def normalize_memory_priority(value: Any) -> tuple[int, MemoryNotePrioritySource]:
    """Return normalized memory priority and source state for a present value."""
    if type(value) is int and value >= 0:
        return value, "frontmatter"
    return DEFAULT_MEMORY_PRIORITY, "invalid"


def _normalized_priority(value: Any) -> tuple[int, MemoryNotePrioritySource]:
    return normalize_memory_priority(value)


def collapse_description(description: str | None) -> str | None:
    """Return a one-line description for compact display surfaces."""
    if description is None:
        return None
    return _normalized_scalar(description)


def normalize_memory_note_type(value: str | None) -> str | None:
    """Return the canonical memory note type for current or legacy spelling."""
    if value is None:
        return None
    return _LEGACY_NOTE_TYPES.get(value, value)


def parse_memory_note_text(text: str, path: str | Path) -> MemoryNote:
    """Parse a markdown memory note from ``text`` and root-relative ``path``."""
    relative_path = Path(path)
    block = _parse_frontmatter_block(text)
    frontmatter = block.frontmatter

    raw_type = frontmatter.get("type")
    if "type" in frontmatter:
        parsed_type = _normalized_scalar(raw_type)
        normalized_type = normalize_memory_note_type(parsed_type)
        note_type = (
            normalized_type if normalized_type in _VALID_NOTE_TYPES else parsed_type
        )
        type_source: MemoryNoteTypeSource = (
            "frontmatter" if normalized_type in _VALID_NOTE_TYPES else "invalid"
        )
    else:
        note_type = None
        type_source = "missing"

    raw_parent = frontmatter.get("parent")
    if "parent" in frontmatter:
        parsed_parent = _normalized_path_scalar(raw_parent)
        parent = parsed_parent or AGENTS_PARENT
        parent_source: MemoryNoteParentSource = (
            "frontmatter" if parsed_parent is not None else "invalid"
        )
    else:
        parent = AGENTS_PARENT
        parent_source = "missing"

    if "priority" in frontmatter:
        priority, priority_source = _normalized_priority(frontmatter["priority"])
    else:
        priority = DEFAULT_MEMORY_PRIORITY
        priority_source = "missing"
    description = _normalized_description(frontmatter.get("description"))

    return MemoryNote(
        path=relative_path,
        type=note_type,
        parent=parent,
        description=description,
        body=block.body,
        frontmatter=frontmatter,
        type_source=type_source,
        parent_source=parent_source,
        priority=priority,
        priority_source=priority_source,
    )


def _iter_discoverable_memory_paths(
    root: Path, *, source_memory_root: Path | None = None
) -> tuple[Path, ...]:
    memory_root = source_memory_root or memory_read_root(root)
    if memory_root is None:
        return ()
    if not memory_root.exists():
        return ()

    paths: list[Path] = []
    paths.extend(
        path
        for path in memory_root.glob("*.md")
        if path.is_file() and path.name != README_FILENAME
    )
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def discover_memory_notes(
    root: Path, *, source_memory_root: Path | None = None
) -> tuple[MemoryNote, ...]:
    """Discover flat memory notes under ``root``."""
    root_resolved = root.resolve(strict=False)
    notes: list[MemoryNote] = []
    memory_root = (
        source_memory_root.resolve(strict=False)
        if source_memory_root is not None
        else None
    )
    for path in _iter_discoverable_memory_paths(
        root_resolved, source_memory_root=memory_root
    ):
        source_relative_path = path.relative_to(root_resolved)
        note_relative_path = path.relative_to(memory_root or path.parent)
        parsed = parse_memory_note_text(
            path.read_text(encoding="utf-8"),
            CANONICAL_MEMORY_RELATIVE_ROOT / note_relative_path,
        )
        notes.append(
            replace(
                parsed,
                parent=canonical_memory_reference(parsed.parent).as_posix(),
                source_path=source_relative_path,
            )
        )
    return tuple(notes)


def _render_memory_frontmatter(
    *,
    note_type: str,
    parent: str,
    priority: int | None = None,
    description: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Render canonical YAML frontmatter for a memory note."""
    data: dict[str, Any] = {
        "type": note_type.strip(),
        "parent": parent.strip().replace("\\", "/"),
    }
    if priority is not None and priority != DEFAULT_MEMORY_PRIORITY:
        data["priority"] = priority
    if description is not None:
        normalized_description = _normalized_description(description)
        if normalized_description is not None:
            if "\n" in normalized_description and not _block_safe_literal_scalar(
                normalized_description
            ):
                normalized_description = collapse_description(normalized_description)
            data["description"] = normalized_description
    if extra is not None:
        for key, value in extra.items():
            if key not in _NON_EXTENSION_FRONTMATTER_KEYS:
                data[key] = value

    dumped = cast(
        str,
        yaml.dump(
            data,
            Dumper=_MemoryFrontmatterDumper,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=_YAML_WIDTH,
        ),
    ).strip()
    dumped = _prettier_stable_frontmatter(dumped)
    return f"---\n{dumped}\n---\n\n"


def render_frontmatter_block(data: Mapping[str, Any]) -> str:
    """Render a standalone, prettier-stable YAML frontmatter block for *data*.

    Unlike :func:`apply_memory_frontmatter`, this declares no ``type:`` or
    ``parent:`` — a memory-web strand must not carry either.
    """
    dumped = cast(
        str,
        yaml.dump(
            dict(data),
            Dumper=_MemoryFrontmatterDumper,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=_YAML_WIDTH,
        ),
    ).strip()
    dumped = _prettier_stable_frontmatter(dumped)
    return f"---\n{dumped}\n---\n\n"


_FRONTMATTER_SCALAR_LINE_RE = re.compile(r"^([a-zA-Z_][\w-]*): (.+)$")


def _prettier_stable_frontmatter(dumped: str) -> str:
    """Return frontmatter shaped the same way Prettier will keep it."""
    # Shaped deliberately to match what prettier would keep at the configured
    # prose width, so a wrapped long scalar (`description:`, `summary:`, …)
    # survives `fmt-md-check`. Resolved here rather than at import time so
    # the value follows `markdown.print_width`.
    # Literal block scalars pass through untouched: the `description: |-`
    # header is short enough to skip wrapping, and indented block-body lines
    # are not treated as YAML sequence items.
    frontmatter_wrap_width = markdown_print_width()
    lines: list[str] = []
    in_sequence = False
    for line in dumped.splitlines():
        match = _FRONTMATTER_SCALAR_LINE_RE.match(line)
        if (
            match is not None
            and len(line) > frontmatter_wrap_width
            and _can_wrap_plain_description(match.group(2))
        ):
            lines.append(f"{match.group(1)}:")
            wrapper = textwrap.TextWrapper(
                width=frontmatter_wrap_width,
                initial_indent="  ",
                subsequent_indent="  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
            lines.extend(wrapper.wrap(match.group(2)))
            in_sequence = False
            continue
        if in_sequence and line.startswith("- "):
            lines.append(f"  {line}")
            continue
        lines.append(line)
        in_sequence = line.endswith(":")
    return "\n".join(lines)


def _can_wrap_plain_description(value: str) -> bool:
    return ": " not in value and "#" not in value and "\t" not in value


def _block_safe_literal_scalar(value: str) -> bool:
    for line in value.splitlines():
        if line != line.rstrip():
            return False
        if line.strip() in {"---", "..."}:
            return False
    return True


def _memory_frontmatter_str_representer(
    dumper: _MemoryFrontmatterDumper,
    value: str,
) -> yaml.nodes.ScalarNode:
    style = "|" if "\n" in value and _block_safe_literal_scalar(value) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_MemoryFrontmatterDumper.add_representer(str, _memory_frontmatter_str_representer)


def apply_memory_frontmatter(
    text: str,
    *,
    note_type: str,
    parent: str = AGENTS_PARENT,
    priority: int | None = None,
    description: str | None = None,
    extra: Mapping[str, Any] | None = None,
    preserve_existing_extra: bool = True,
    preserve_existing_priority: bool = True,
) -> str:
    """Apply canonical memory frontmatter to existing markdown text."""
    block = _parse_frontmatter_block(text)
    if priority is None and preserve_existing_priority:
        if "priority" in block.frontmatter:
            parsed_priority, priority_source = _normalized_priority(
                block.frontmatter["priority"]
            )
            if priority_source == "frontmatter":
                priority = parsed_priority
    preserved_extra: dict[str, Any] = {}
    if preserve_existing_extra:
        preserved_extra.update(
            {
                key: value
                for key, value in block.frontmatter.items()
                if key not in _NON_EXTENSION_FRONTMATTER_KEYS
            }
        )
    if extra is not None:
        preserved_extra.update(
            {
                key: value
                for key, value in extra.items()
                if key not in _NON_EXTENSION_FRONTMATTER_KEYS
            }
        )

    body = block.body.lstrip("\n")
    return (
        _render_memory_frontmatter(
            note_type=note_type,
            parent=parent,
            priority=priority,
            description=description,
            extra=preserved_extra,
        )
        + body
    )


def _parent_key(parent: MemoryNote | str | Path) -> str:
    if isinstance(parent, MemoryNote):
        return parent.relative_path
    if isinstance(parent, Path):
        return parent.as_posix()
    return parent.strip().replace("\\", "/")


def _parent_keys(parent: MemoryNote | str | Path) -> frozenset[str]:
    key = _parent_key(parent)
    if not isinstance(parent, MemoryNote):
        return frozenset({key})
    prefix = "sase/memory/"
    keys = {key}
    if key.startswith(prefix):
        keys.add(key[len(prefix) :])
    return frozenset(keys)


def _children_of(
    notes: Iterable[MemoryNote],
    parent: MemoryNote | str | Path,
) -> tuple[MemoryNote, ...]:
    """Return reference notes parented under ``parent``, sorted by path."""
    keys = _parent_keys(parent)
    children = [
        note for note in notes if note.type == "reference" and note.parent in keys
    ]
    return tuple(sorted(children, key=lambda note: note.relative_path))


def _render_memory_note_references(notes: Iterable[MemoryNote]) -> str:
    """Render notes in the reference-memory list shape."""
    lines: list[str] = []
    reference_notes = sorted(
        (note for note in notes if note.type == "reference"),
        key=lambda note: note.relative_path,
    )
    for index, note in enumerate(reference_notes):
        if index:
            lines.append("")
        lines.append(f"**`{note.relative_path}`**  ")
        lines.append(note.description or "")
    return "\n".join(lines)


def render_long_memory_sections(notes: Iterable[MemoryNote]) -> str:
    """Render reference notes as AGENTS.md Tier 2 H3 subsections."""
    lines: list[str] = []
    reference_notes = sorted(
        (note for note in notes if note.type == "reference"),
        key=lambda note: note.relative_path,
    )
    for index, note in enumerate(reference_notes):
        if index:
            lines.append("")
        lines.append(f"### `{note.relative_path}`")
        if note.description:
            lines.append("")
            lines.append(note.description)
    return "\n".join(lines)


def render_children_section(
    notes: Iterable[MemoryNote],
    parent: MemoryNote | str | Path,
) -> str:
    """Render a ``## Children`` section for ``parent`` or return ``""``."""
    references = _render_memory_note_references(_children_of(notes, parent))
    if not references:
        return ""
    return (
        "## Children\n\n"
        "The below files contain detailed reference material. When working in their "
        "domain, you\n"
        "MUST use your `/sase_memory_read` skill to review their contents. Do not "
        "read canonical\n"
        "memory files directly.\n\n"
        f"{references}\n"
    )


__all__ = [
    "AGENTS_PARENT",
    "DEFAULT_MEMORY_PRIORITY",
    "GeneratedShortMemoryNote",
    "GeneratedLongMemoryNote",
    "MEMORY_DIR",
    "MemoryNote",
    "MemoryNoteParentSource",
    "MemoryNotePrioritySource",
    "MemoryNoteType",
    "MemoryNoteTypeSource",
    "README_FILENAME",
    "apply_memory_frontmatter",
    "collapse_description",
    "discover_memory_notes",
    "normalize_memory_priority",
    "normalize_memory_note_type",
    "parse_memory_note_text",
    "render_children_section",
    "render_frontmatter_block",
    "render_long_memory_sections",
]
