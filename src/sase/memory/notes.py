"""Memory note parsing, discovery, and rendering helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import textwrap
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

AGENTS_PARENT = "AGENTS.md"
MEMORY_DIR = "memory"
README_FILENAME = "README.md"

MemoryNoteType = Literal["short", "long"]
MemoryNoteTypeSource = Literal["frontmatter", "missing", "invalid"]
MemoryNoteParentSource = Literal["frontmatter", "missing", "invalid"]

_VALID_NOTE_TYPES = frozenset({"short", "long"})
_CANONICAL_FRONTMATTER_KEYS = frozenset({"type", "parent", "description"})
_RETIRED_FRONTMATTER_KEYS = frozenset({"keywords"})
_NON_EXTENSION_FRONTMATTER_KEYS = (
    _CANONICAL_FRONTMATTER_KEYS | _RETIRED_FRONTMATTER_KEYS
)
_YAML_WIDTH = 1_000_000
_FRONTMATTER_WRAP_WIDTH = 120


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

    @property
    def relative_path(self) -> str:
        """Return the root-relative note path in POSIX form."""
        return self.path.as_posix()


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


def _normalized_path_scalar(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("\\", "/")
    return normalized or None


def parse_memory_note_text(text: str, path: str | Path) -> MemoryNote:
    """Parse a markdown memory note from ``text`` and root-relative ``path``."""
    relative_path = Path(path)
    block = _parse_frontmatter_block(text)
    frontmatter = block.frontmatter

    raw_type = frontmatter.get("type")
    if "type" in frontmatter:
        parsed_type = _normalized_scalar(raw_type)
        note_type = parsed_type
        type_source: MemoryNoteTypeSource = (
            "frontmatter" if parsed_type in _VALID_NOTE_TYPES else "invalid"
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

    description = _normalized_scalar(frontmatter.get("description"))

    return MemoryNote(
        path=relative_path,
        type=note_type,
        parent=parent,
        description=description,
        body=block.body,
        frontmatter=frontmatter,
        type_source=type_source,
        parent_source=parent_source,
    )


def _iter_discoverable_memory_paths(root: Path) -> tuple[Path, ...]:
    memory_root = root / MEMORY_DIR
    if not memory_root.exists():
        return ()

    paths: list[Path] = []
    paths.extend(
        path
        for path in memory_root.glob("*.md")
        if path.is_file() and path.name != README_FILENAME
    )
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def discover_memory_notes(root: Path) -> tuple[MemoryNote, ...]:
    """Discover flat memory notes under ``root``."""
    root_resolved = root.resolve(strict=False)
    notes: list[MemoryNote] = []
    for path in _iter_discoverable_memory_paths(root_resolved):
        relative_path = path.relative_to(root_resolved)
        notes.append(
            parse_memory_note_text(
                path.read_text(encoding="utf-8"),
                relative_path,
            )
        )
    return tuple(notes)


def _render_memory_frontmatter(
    *,
    note_type: str,
    parent: str,
    description: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Render canonical YAML frontmatter for a memory note."""
    data: dict[str, Any] = {
        "type": note_type.strip(),
        "parent": parent.strip().replace("\\", "/"),
    }
    if description is not None:
        data["description"] = " ".join(description.split())
    if extra is not None:
        for key, value in extra.items():
            if key not in _NON_EXTENSION_FRONTMATTER_KEYS:
                data[key] = value

    dumped = cast(
        str,
        yaml.safe_dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=_YAML_WIDTH,
        ),
    ).strip()
    dumped = _prettier_stable_frontmatter(dumped)
    return f"---\n{dumped}\n---\n\n"


def _prettier_stable_frontmatter(dumped: str) -> str:
    """Return frontmatter shaped the same way Prettier will keep it."""
    lines: list[str] = []
    in_sequence = False
    for line in dumped.splitlines():
        prefix = "description: "
        value = line.removeprefix(prefix)
        if (
            line.startswith(prefix)
            and len(line) > _FRONTMATTER_WRAP_WIDTH
            and _can_wrap_plain_description(value)
        ):
            lines.append("description:")
            wrapper = textwrap.TextWrapper(
                width=_FRONTMATTER_WRAP_WIDTH - 2,
                initial_indent="  ",
                subsequent_indent="  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
            lines.extend(wrapper.wrap(value))
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


def apply_memory_frontmatter(
    text: str,
    *,
    note_type: str,
    parent: str = AGENTS_PARENT,
    description: str | None = None,
    extra: Mapping[str, Any] | None = None,
    preserve_existing_extra: bool = True,
) -> str:
    """Apply canonical memory frontmatter to existing markdown text."""
    block = _parse_frontmatter_block(text)
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


def _children_of(
    notes: Iterable[MemoryNote],
    parent: MemoryNote | str | Path,
) -> tuple[MemoryNote, ...]:
    """Return long-term notes parented under ``parent``, sorted by path."""
    key = _parent_key(parent)
    children = [note for note in notes if note.type == "long" and note.parent == key]
    return tuple(sorted(children, key=lambda note: note.relative_path))


def render_memory_note_references(notes: Iterable[MemoryNote]) -> str:
    """Render notes in the AGENTS.md long-memory reference-list shape."""
    lines: list[str] = []
    long_notes = sorted(
        (note for note in notes if note.type == "long"),
        key=lambda note: note.relative_path,
    )
    for index, note in enumerate(long_notes):
        if index:
            lines.append("")
        lines.append(f"**`{note.relative_path}`**  ")
        lines.append(note.description or "")
    return "\n".join(lines)


def render_children_section(
    notes: Iterable[MemoryNote],
    parent: MemoryNote | str | Path,
) -> str:
    """Render a ``## Children`` section for ``parent`` or return ``""``."""
    references = render_memory_note_references(_children_of(notes, parent))
    if not references:
        return ""
    return f"## Children\n\n{references}\n"


__all__ = [
    "AGENTS_PARENT",
    "MEMORY_DIR",
    "MemoryNote",
    "MemoryNoteParentSource",
    "MemoryNoteType",
    "MemoryNoteTypeSource",
    "README_FILENAME",
    "apply_memory_frontmatter",
    "discover_memory_notes",
    "parse_memory_note_text",
    "render_children_section",
    "render_memory_note_references",
]
