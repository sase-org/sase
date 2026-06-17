"""Memory note parsing, discovery, and validation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import textwrap
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

AGENTS_PARENT = "AGENTS.md"
MEMORY_DIR = "memory"
README_FILENAME = "README.md"

MemoryNoteType = Literal["short", "long"]
MemoryNoteTypeSource = Literal["frontmatter", "legacy_path", "missing", "invalid"]
MemoryNoteParentSource = Literal["frontmatter", "default", "invalid"]

_VALID_NOTE_TYPES = frozenset({"short", "long"})
_LEGACY_TYPE_DIRS: Mapping[str, MemoryNoteType] = {
    "short": "short",
    "long": "long",
}
_CANONICAL_FRONTMATTER_KEYS = frozenset({"type", "parent", "description"})
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
class MemoryNoteValidationError:
    """A validation error tied to one memory note."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


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


def split_frontmatter(text: str) -> tuple[Mapping[str, Any], str]:
    """Split one leading YAML frontmatter block from ``text`` if present."""
    block = _parse_frontmatter_block(text)
    return block.frontmatter, block.body


def _legacy_type_from_path(path: Path) -> MemoryNoteType | None:
    parts = path.parts
    if len(parts) >= 3 and parts[0] == MEMORY_DIR:
        return _LEGACY_TYPE_DIRS.get(parts[1])
    return None


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
        note_type = _legacy_type_from_path(relative_path)
        type_source = "legacy_path" if note_type is not None else "missing"

    raw_parent = frontmatter.get("parent")
    if "parent" in frontmatter:
        parsed_parent = _normalized_path_scalar(raw_parent)
        parent = parsed_parent or AGENTS_PARENT
        parent_source: MemoryNoteParentSource = (
            "frontmatter" if parsed_parent is not None else "invalid"
        )
    else:
        parent = AGENTS_PARENT
        parent_source = "default"

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


def read_memory_note(root: Path, path: str | Path) -> MemoryNote:
    """Read and parse one memory note under ``root``."""
    root_resolved = root.resolve(strict=False)
    candidate = Path(path)
    note_path = candidate if candidate.is_absolute() else root_resolved / candidate
    relative_path = note_path.relative_to(root_resolved)
    return parse_memory_note_text(
        note_path.read_text(encoding="utf-8"),
        relative_path,
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
    for tier in sorted(_LEGACY_TYPE_DIRS):
        tier_root = memory_root / tier
        if not tier_root.exists():
            continue
        paths.extend(
            path
            for path in tier_root.rglob("*.md")
            if path.is_file() and path.name != README_FILENAME
        )
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def discover_memory_notes(root: Path) -> tuple[MemoryNote, ...]:
    """Discover flat and legacy nested memory notes under ``root``."""
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


def uses_legacy_memory_layout(root: Path) -> bool:
    """Return whether ``root`` still has legacy ``memory/short|long`` dirs."""
    memory_root = root / MEMORY_DIR
    return any((memory_root / tier).exists() for tier in _LEGACY_TYPE_DIRS)


def render_memory_frontmatter(
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
            if key not in _CANONICAL_FRONTMATTER_KEYS:
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
                if key not in _CANONICAL_FRONTMATTER_KEYS
            }
        )
    if extra is not None:
        preserved_extra.update(
            {
                key: value
                for key, value in extra.items()
                if key not in _CANONICAL_FRONTMATTER_KEYS
            }
        )

    body = block.body.lstrip("\n")
    return (
        render_memory_frontmatter(
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


def children_of(
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
    references = render_memory_note_references(children_of(notes, parent))
    if not references:
        return ""
    return f"## Children\n\n{references}\n"


def _validation_error(note: MemoryNote, message: str) -> MemoryNoteValidationError:
    return MemoryNoteValidationError(path=note.relative_path, message=message)


def _valid_parent_path(parent: str) -> bool:
    if parent == AGENTS_PARENT:
        return True
    path = PurePosixPath(parent)
    if path.is_absolute():
        return False
    parts = path.parts
    return (
        len(parts) >= 2
        and parts[0] == MEMORY_DIR
        and path.suffix == ".md"
        and path.name != README_FILENAME
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _validate_required_frontmatter(
    note: MemoryNote,
    *,
    require_frontmatter: bool,
) -> list[MemoryNoteValidationError]:
    errors: list[MemoryNoteValidationError] = []
    if note.type_source == "missing":
        errors.append(_validation_error(note, "missing type frontmatter"))
    elif note.type not in _VALID_NOTE_TYPES:
        errors.append(_validation_error(note, "invalid memory note type"))
    elif require_frontmatter and note.type_source != "frontmatter":
        errors.append(_validation_error(note, "missing type frontmatter"))

    if note.parent_source == "invalid":
        errors.append(_validation_error(note, "invalid parent frontmatter"))
    elif require_frontmatter and note.parent_source != "frontmatter":
        errors.append(_validation_error(note, "missing parent frontmatter"))

    if not _valid_parent_path(note.parent):
        errors.append(_validation_error(note, "invalid parent path"))

    raw_description = note.frontmatter.get("description")
    if "description" in note.frontmatter and not isinstance(raw_description, str):
        errors.append(_validation_error(note, "invalid description frontmatter"))
    elif require_frontmatter and note.type == "long" and not note.description:
        errors.append(
            _validation_error(note, "long memory notes require a description")
        )
    return errors


def _duplicate_flat_name_errors(
    notes: tuple[MemoryNote, ...],
) -> list[MemoryNoteValidationError]:
    notes_by_name: dict[str, list[MemoryNote]] = {}
    for note in notes:
        notes_by_name.setdefault(note.path.name, []).append(note)

    errors: list[MemoryNoteValidationError] = []
    for name, duplicates in sorted(notes_by_name.items()):
        if len(duplicates) <= 1:
            continue
        for note in duplicates:
            errors.append(
                _validation_error(
                    note,
                    f"duplicate flat memory filename: {name}",
                )
            )
    return errors


def _parent_graph_errors(
    notes: tuple[MemoryNote, ...],
) -> list[MemoryNoteValidationError]:
    notes_by_path = {note.relative_path: note for note in notes}
    errors: list[MemoryNoteValidationError] = []
    for note in notes:
        if note.parent == AGENTS_PARENT or not _valid_parent_path(note.parent):
            continue

        parent = notes_by_path.get(note.parent)
        if parent is None:
            errors.append(
                _validation_error(note, f"parent memory note not found: {note.parent}")
            )
            continue

        if note.type == "short":
            errors.append(
                _validation_error(
                    note,
                    "short memory notes must use parent AGENTS.md",
                )
            )
        if parent.type != "long":
            errors.append(
                _validation_error(
                    note,
                    "parent must be AGENTS.md or a long memory note",
                )
            )
    return errors


def _cycle_errors(notes: tuple[MemoryNote, ...]) -> list[MemoryNoteValidationError]:
    notes_by_path = {note.relative_path: note for note in notes}
    reported_cycles: set[frozenset[str]] = set()
    errors: list[MemoryNoteValidationError] = []

    for note in notes:
        order: list[str] = []
        seen: dict[str, int] = {}
        current: MemoryNote | None = note
        while current is not None and current.type == "long":
            current_path = current.relative_path
            if current_path in seen:
                cycle = order[seen[current_path] :]
                cycle_key = frozenset(cycle)
                if cycle_key not in reported_cycles:
                    reported_cycles.add(cycle_key)
                    cycle_text = " -> ".join([*cycle, current_path])
                    for path in cycle:
                        errors.append(
                            _validation_error(
                                notes_by_path[path],
                                f"memory note parent cycle: {cycle_text}",
                            )
                        )
                break

            seen[current_path] = len(order)
            order.append(current_path)
            if current.parent == AGENTS_PARENT:
                break
            parent = notes_by_path.get(current.parent)
            if parent is None or parent.type != "long":
                break
            current = parent

    return errors


def validate_notes(
    notes: Iterable[MemoryNote],
    *,
    require_frontmatter: bool = True,
) -> tuple[MemoryNoteValidationError, ...]:
    """Validate memory note frontmatter and parent/child relationships."""
    note_tuple = tuple(sorted(notes, key=lambda note: note.relative_path))
    errors: list[MemoryNoteValidationError] = []
    for note in note_tuple:
        errors.extend(
            _validate_required_frontmatter(
                note,
                require_frontmatter=require_frontmatter,
            )
        )
    errors.extend(_duplicate_flat_name_errors(note_tuple))
    errors.extend(_parent_graph_errors(note_tuple))
    errors.extend(_cycle_errors(note_tuple))
    return tuple(errors)


__all__ = [
    "AGENTS_PARENT",
    "MEMORY_DIR",
    "MemoryNote",
    "MemoryNoteParentSource",
    "MemoryNoteType",
    "MemoryNoteTypeSource",
    "MemoryNoteValidationError",
    "README_FILENAME",
    "apply_memory_frontmatter",
    "children_of",
    "discover_memory_notes",
    "parse_memory_note_text",
    "read_memory_note",
    "render_children_section",
    "render_memory_frontmatter",
    "render_memory_note_references",
    "split_frontmatter",
    "uses_legacy_memory_layout",
    "validate_notes",
]
