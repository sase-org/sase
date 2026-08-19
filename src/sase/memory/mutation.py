"""CLI-free create/update/delete engine for SASE memory notes.

This module is the only code that writes memory notes. It has no Textual
import. Validation is pure; disk writes are atomic and digest-guarded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Literal

from sase.content_layout import LayoutCollisionError
from sase.core.paths import sase_home
from sase.core.time import local_now
from sase.main.init_memory.root_rendering import generated_memory_note_relative_paths
from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    MemoryNoteType,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_note_relative_path,
    memory_read_root,
    memory_write_root,
)

MemoryScopeKind = Literal["project", "home"]
MemoryDraftField = Literal["stem", "type", "parent", "description"]

_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_README_STEM = "readme"
_BACKUP_DIRNAME = "memory-backups"


@dataclass(frozen=True, slots=True)
class MemoryNoteDraft:
    """A normalized memory-note draft that passed structural checks."""

    stem: str
    relative_path: str
    note_type: MemoryNoteType
    parent: str
    description: str | None


@dataclass(frozen=True, slots=True)
class MemoryDraftValidation:
    """Per-field diagnostics for a memory-note draft.

    ``by_field`` only contains keys that have at least one message so a form
    can render errors inline. ``draft`` is set when stem/type/parent parsed
    far enough to name the candidate note, even if other fields still fail.
    """

    draft: MemoryNoteDraft | None
    by_field: Mapping[MemoryDraftField, tuple[str, ...]]

    def __bool__(self) -> bool:
        return not self.by_field and self.draft is not None


@dataclass(frozen=True, slots=True)
class MemoryMutationOutcome:
    """Result of a successful memory-note create, update, or delete."""

    scope_key: str
    content_root: Path
    relative_path: str
    stem: str
    type: MemoryNoteType
    parent: str
    description: str | None
    backup_path: Path | None = None


class MemoryMutationError(RuntimeError):
    """Raised when a memory-note mutation cannot be applied."""


class MemoryValidationError(MemoryMutationError):
    """Raised when a draft fails field validation."""

    def __init__(self, validation: MemoryDraftValidation) -> None:
        self.validation = validation
        parts = [
            f"{field}: {message}"
            for field, messages in validation.by_field.items()
            for message in messages
        ]
        super().__init__("; ".join(parts) or "memory note draft is invalid")


class MemoryConflictError(MemoryMutationError):
    """Raised when the note changed between preview and write."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"memory note changed after preview: {path}; reload and retry the edit"
        )


class MemoryGeneratedNoteError(MemoryMutationError):
    """Raised when a generated memory note is the mutation target."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        super().__init__(f"generated memory note is read-only: {relative_path}")


def memory_note_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of a memory note's on-disk bytes."""
    return hashlib.sha256(data).hexdigest()


def memory_note_relative_path_for_stem(stem: str) -> str:
    """Return the canonical root-relative path for a flat memory-note stem."""
    return (CANONICAL_MEMORY_RELATIVE_ROOT / f"{stem}.md").as_posix()


def validate_memory_note_draft(
    *,
    stem: str,
    note_type: str,
    parent: str,
    description: str | None,
    existing_notes: Sequence[MemoryNote] = (),
    current_relative_path: str | None = None,
    include_project_memory: bool = True,
) -> MemoryDraftValidation:
    """Return per-field diagnostics for a create or update draft.

    This function is pure: it does not read or write the filesystem. Callers
    pass the scope's already-loaded notes so the panel form can share it.
    """
    errors: dict[MemoryDraftField, list[str]] = {
        "stem": [],
        "type": [],
        "parent": [],
        "description": [],
    }
    parsed_stem, stem_errors = _parse_stem(stem)
    errors["stem"].extend(stem_errors)

    cleaned_type = note_type.strip()
    parsed_type: MemoryNoteType | None
    if cleaned_type == "short":
        parsed_type = "short"
    elif cleaned_type == "long":
        parsed_type = "long"
    else:
        parsed_type = None
        errors["type"].append("memory note type must be short or long")

    parsed_parent, parent_parse_errors = _parse_parent(parent)
    errors["parent"].extend(parent_parse_errors)

    current_canonical = (
        _canonical_flat_note_path(current_relative_path)
        if current_relative_path is not None
        else None
    )
    relative_path: str | None = None
    if current_canonical is not None:
        relative_path = current_canonical
    elif parsed_stem is not None:
        relative_path = memory_note_relative_path_for_stem(parsed_stem)

    if relative_path is not None and _is_generated_relative_path(
        relative_path, include_project_memory=include_project_memory
    ):
        errors["stem"].append(f"generated memory note is read-only: {relative_path}")

    notes_by_path = {note.relative_path: note for note in existing_notes}
    if (
        relative_path is not None
        and relative_path in notes_by_path
        and relative_path != current_canonical
    ):
        errors["stem"].append(f"a memory note already exists at {relative_path}")

    parsed_description = _normalize_description(description)
    if parsed_type == "long" and parsed_description is None:
        errors["description"].append("long memory notes require a description")

    if parsed_type == "short" and parsed_parent is not None:
        if parsed_parent != AGENTS_PARENT:
            errors["parent"].append("short memory notes must parent to AGENTS.md")

    if (
        parsed_type == "long"
        and parsed_parent is not None
        and parsed_parent != AGENTS_PARENT
        and relative_path is not None
    ):
        errors["parent"].extend(
            _parent_legality_errors(
                note_relative_path=relative_path,
                parent=parsed_parent,
                notes_by_path=notes_by_path,
            )
        )

    if current_canonical is not None and parsed_type is not None:
        children = _children_of(existing_notes, current_canonical)
        if children and parsed_type != "long":
            named = ", ".join(child.relative_path for child in children)
            errors["type"].append(
                f"cannot change type to short while children exist ({named})"
            )

    draft: MemoryNoteDraft | None = None
    if (
        parsed_stem is not None
        and parsed_type is not None
        and parsed_parent is not None
    ):
        draft = MemoryNoteDraft(
            stem=Path(
                relative_path or memory_note_relative_path_for_stem(parsed_stem)
            ).stem,
            relative_path=relative_path
            or memory_note_relative_path_for_stem(parsed_stem),
            note_type=parsed_type,
            parent=parsed_parent,
            description=parsed_description,
        )

    by_field = {
        field: tuple(messages) for field, messages in errors.items() if messages
    }
    return MemoryDraftValidation(draft=draft, by_field=by_field)


def create_memory_note(
    *,
    scope_key: str,
    content_root: Path | str,
    stem: str,
    note_type: str,
    parent: str = AGENTS_PARENT,
    description: str | None = None,
    body: str = "",
    scope_kind: MemoryScopeKind = "project",
) -> MemoryMutationOutcome:
    """Create a new flat memory note under the scope's write root."""
    root = _resolve_content_root(content_root)
    include_project_memory = scope_kind == "project"
    notes = _discover_notes(root)
    parsed_stem, _stem_errors = _parse_stem(stem)
    if parsed_stem is not None:
        _raise_if_generated(
            memory_note_relative_path_for_stem(parsed_stem),
            include_project_memory,
        )
    validation = validate_memory_note_draft(
        stem=stem,
        note_type=note_type,
        parent=parent,
        description=description,
        existing_notes=notes,
        include_project_memory=include_project_memory,
    )
    draft = _require_valid_draft(validation)
    dest = memory_write_root(root) / f"{draft.stem}.md"
    _assert_flat_memory_path(dest, root)
    if dest.exists():
        raise MemoryMutationError(f"refusing to overwrite existing memory note: {dest}")
    content = apply_memory_frontmatter(
        body,
        note_type=draft.note_type,
        parent=draft.parent,
        description=draft.description,
    )
    _write_bytes_atomically(dest, content.encode("utf-8"), overwrite=False)
    return MemoryMutationOutcome(
        scope_key=scope_key,
        content_root=root,
        relative_path=draft.relative_path,
        stem=draft.stem,
        type=draft.note_type,
        parent=draft.parent,
        description=draft.description,
    )


def update_memory_note(
    *,
    scope_key: str,
    content_root: Path | str,
    relative_path: str,
    note_type: str,
    parent: str,
    description: str | None,
    expected_digest: str,
    scope_kind: MemoryScopeKind = "project",
) -> MemoryMutationOutcome:
    """Rewrite a note's frontmatter, preserving the body byte-for-byte."""
    root = _resolve_content_root(content_root)
    include_project_memory = scope_kind == "project"
    canonical = _require_flat_note_path(relative_path)
    _raise_if_generated(canonical, include_project_memory)
    notes = _discover_notes(root)
    note = _require_existing_note(notes, canonical)
    source = _note_source_path(root, note)
    _assert_flat_memory_path(source, root)
    original = _read_note_bytes(source)
    _require_digest(source, original, expected_digest)
    validation = validate_memory_note_draft(
        stem=note.path.stem,
        note_type=note_type,
        parent=parent,
        description=description,
        existing_notes=notes,
        current_relative_path=canonical,
        include_project_memory=include_project_memory,
    )
    draft = _require_valid_draft(validation)
    original_text = original.decode("utf-8")
    parsed_original = parse_memory_note_text(original_text, canonical)
    updated = apply_memory_frontmatter(
        original_text,
        note_type=draft.note_type,
        parent=draft.parent,
        description=draft.description,
    )
    parsed_updated = parse_memory_note_text(updated, canonical)
    if parsed_updated.body != parsed_original.body:
        updated = (
            _frontmatter_prefix(updated, parsed_updated.body) + parsed_original.body
        )
    _write_bytes_atomically(source, updated.encode("utf-8"), overwrite=True)
    return MemoryMutationOutcome(
        scope_key=scope_key,
        content_root=root,
        relative_path=canonical,
        stem=note.path.stem,
        type=draft.note_type,
        parent=draft.parent,
        description=draft.description,
    )


def delete_memory_note(
    *,
    scope_key: str,
    content_root: Path | str,
    relative_path: str,
    expected_digest: str,
    scope_kind: MemoryScopeKind = "project",
) -> MemoryMutationOutcome:
    """Backup and unlink a memory note after a digest check."""
    root = _resolve_content_root(content_root)
    include_project_memory = scope_kind == "project"
    canonical = _require_flat_note_path(relative_path)
    _raise_if_generated(canonical, include_project_memory)
    notes = _discover_notes(root)
    note = _require_existing_note(notes, canonical)
    children = _children_of(notes, canonical)
    if children:
        named = ", ".join(child.relative_path for child in children)
        raise MemoryMutationError(
            f"cannot delete {canonical}: reparent children first ({named})"
        )
    source = _note_source_path(root, note)
    _assert_flat_memory_path(source, root)
    original = _read_note_bytes(source)
    _require_digest(source, original, expected_digest)
    backup_path = _backup_path(
        content_root=root,
        scope_key=scope_key,
        scope_kind=scope_kind,
        stem=note.path.stem,
    )
    _write_bytes_atomically(backup_path, original, overwrite=False)
    current = _read_note_bytes(source)
    if current != original:
        raise MemoryConflictError(source)
    source.unlink()
    resolved_type: MemoryNoteType = "short" if note.type == "short" else "long"
    return MemoryMutationOutcome(
        scope_key=scope_key,
        content_root=root,
        relative_path=canonical,
        stem=note.path.stem,
        type=resolved_type,
        parent=note.parent,
        description=note.description,
        backup_path=backup_path,
    )


def _require_valid_draft(validation: MemoryDraftValidation) -> MemoryNoteDraft:
    if validation.by_field or validation.draft is None:
        raise MemoryValidationError(validation)
    return validation.draft


def _raise_if_generated(relative_path: str, include_project_memory: bool) -> None:
    if _is_generated_relative_path(
        relative_path, include_project_memory=include_project_memory
    ):
        raise MemoryGeneratedNoteError(relative_path)


def _is_generated_relative_path(
    relative_path: str, *, include_project_memory: bool
) -> bool:
    generated = {
        path.as_posix()
        for path in generated_memory_note_relative_paths(
            include_project_memory=include_project_memory
        )
    }
    return relative_path in generated


def _parse_stem(raw: str) -> tuple[str | None, tuple[str, ...]]:
    cleaned = raw.strip()
    if cleaned.lower().endswith(".md"):
        cleaned = cleaned[:-3]
    if not cleaned:
        return None, ("memory note stem is required",)
    path = Path(cleaned.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None, (
            "memory note stem must be a single flat segment without traversal",
        )
    if len(path.parts) != 1:
        return None, ("memory note stem must be a single flat segment",)
    if cleaned.lower() == _README_STEM:
        return None, ("memory note stem cannot be README",)
    if not _STEM_RE.fullmatch(cleaned):
        return None, ("memory note stem must match [A-Za-z0-9][A-Za-z0-9_-]*",)
    return cleaned, ()


def _parse_parent(raw: str) -> tuple[str | None, tuple[str, ...]]:
    cleaned = raw.strip().replace("\\", "/")
    if not cleaned or cleaned == AGENTS_PARENT:
        return AGENTS_PARENT, ()
    if any(part in {"", ".", ".."} for part in Path(cleaned).parts):
        return None, ("memory note parent must not contain traversal",)
    if Path(cleaned).is_absolute():
        return None, ("memory note parent must be a relative path",)
    relative = memory_note_relative_path(cleaned)
    if relative is None:
        if "/" in cleaned:
            return None, ("memory note parent must be AGENTS.md or a memory note path",)
        stem, stem_errors = _parse_stem(cleaned)
        if stem is None:
            return None, stem_errors or (
                "memory note parent must be AGENTS.md or a memory note path",
            )
        return memory_note_relative_path_for_stem(stem), ()
    if len(relative.parts) != 1 or relative.suffix != ".md":
        return None, ("memory note parent must be a flat memory note",)
    if relative.stem.lower() == _README_STEM:
        return None, ("memory note parent cannot be README.md",)
    return canonical_memory_reference(cleaned).as_posix(), ()


def _parent_legality_errors(
    *,
    note_relative_path: str,
    parent: str,
    notes_by_path: Mapping[str, MemoryNote],
) -> tuple[str, ...]:
    if parent == note_relative_path:
        return ("memory note parent cannot point at the note itself",)
    parent_note = notes_by_path.get(parent)
    if parent_note is None:
        return (f"memory note parent does not exist: {parent}",)
    if parent_note.type == "short":
        return (f"memory note parent is a short note: {parent}",)
    if parent_note.type != "long":
        return (f"memory note parent is not a long note: {parent}",)
    if _parent_chain_contains(
        start=parent,
        target=note_relative_path,
        notes_by_path=notes_by_path,
    ):
        return (f"memory note parent would create a cycle through {parent}",)
    return ()


def _parent_chain_contains(
    *,
    start: str,
    target: str,
    notes_by_path: Mapping[str, MemoryNote],
) -> bool:
    seen: set[str] = set()
    current = start
    while current != AGENTS_PARENT:
        if current == target:
            return True
        if current in seen:
            return True
        seen.add(current)
        parent_note = notes_by_path.get(current)
        if parent_note is None:
            return False
        current = parent_note.parent
    return False


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    probe = apply_memory_frontmatter(
        "",
        note_type="long",
        parent=AGENTS_PARENT,
        description=description,
    )
    return parse_memory_note_text(probe, "sase/memory/_draft.md").description


def _canonical_flat_note_path(raw: str) -> str | None:
    cleaned = raw.strip().replace("\\", "/")
    if not cleaned:
        return None
    path = Path(cleaned)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    relative = memory_note_relative_path(path)
    if relative is None:
        if len(path.parts) == 1 and path.suffix == ".md":
            relative = path
        else:
            return None
    if len(relative.parts) != 1 or relative.suffix != ".md":
        return None
    if relative.stem.lower() == _README_STEM:
        return None
    return (CANONICAL_MEMORY_RELATIVE_ROOT / relative).as_posix()


def _require_flat_note_path(raw: str) -> str:
    canonical = _canonical_flat_note_path(raw)
    if canonical is None:
        raise MemoryMutationError(
            f"memory note path is not a flat note inside the memory root: {raw}"
        )
    return canonical


def _resolve_content_root(content_root: Path | str) -> Path:
    return Path(content_root).expanduser().resolve(strict=False)


def _discover_notes(content_root: Path) -> tuple[MemoryNote, ...]:
    try:
        return discover_memory_notes(content_root)
    except LayoutCollisionError as exc:
        raise MemoryMutationError(str(exc)) from exc
    except OSError as exc:
        raise MemoryMutationError(
            f"failed to read memory notes under {content_root}: {exc}"
        ) from exc


def _require_existing_note(
    notes: Sequence[MemoryNote], relative_path: str
) -> MemoryNote:
    for note in notes:
        if note.relative_path == relative_path:
            return note
    raise MemoryMutationError(f"memory note does not exist: {relative_path}")


def _children_of(
    notes: Sequence[MemoryNote], relative_path: str
) -> tuple[MemoryNote, ...]:
    children = [note for note in notes if note.parent == relative_path]
    return tuple(sorted(children, key=lambda note: note.relative_path))


def _note_source_path(content_root: Path, note: MemoryNote) -> Path:
    relative = note.source_path or note.path
    return (content_root / relative).resolve(strict=False)


def _assert_flat_memory_path(path: Path, content_root: Path) -> None:
    write_root = memory_write_root(content_root)
    try:
        read_root = memory_read_root(content_root)
    except LayoutCollisionError as exc:
        raise MemoryMutationError(str(exc)) from exc
    resolved = path.resolve(strict=False)
    roots = [write_root]
    if read_root is not None:
        roots.append(read_root)
    if any(_is_flat_child(resolved, root) for root in roots):
        return
    raise MemoryMutationError(
        f"memory note path is not a flat note inside the memory root: {path}"
    )


def _is_flat_child(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return len(relative.parts) == 1 and relative.suffix == ".md"


def _read_note_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MemoryMutationError(f"failed to read memory note: {path}") from exc


def _require_digest(path: Path, data: bytes, expected_digest: str) -> None:
    if memory_note_digest(data) != expected_digest:
        raise MemoryConflictError(path)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryMutationError(f"memory note is not valid UTF-8: {path}") from exc


def _frontmatter_prefix(rendered: str, body: str) -> str:
    if body and rendered.endswith(body):
        return rendered[: -len(body)]
    return rendered


def _backup_path(
    *,
    content_root: Path,
    scope_key: str,
    scope_kind: MemoryScopeKind,
    stem: str,
) -> Path:
    if scope_kind == "home":
        backup_dir = sase_home() / _BACKUP_DIRNAME / scope_key
    else:
        backup_dir = content_root / ".sase" / _BACKUP_DIRNAME
    stamp = local_now().strftime("%Y%m%dT%H%M%S")
    candidate = backup_dir / f"{stem}-{stamp}.md"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        numbered = backup_dir / f"{stem}-{stamp}-{suffix:02d}.md"
        if not numbered.exists():
            return numbered
        suffix += 1


def _write_bytes_atomically(path: Path, data: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            if overwrite and path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            else:
                os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temp_path, path)
        else:
            try:
                os.link(temp_path, path)
            except OSError as exc:
                if exc.errno == errno.EEXIST or isinstance(exc, FileExistsError):
                    raise MemoryMutationError(
                        f"refusing to overwrite existing memory note: {path}"
                    ) from exc
                raise
            temp_path.unlink()
        published = True
    finally:
        if not published and temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "MemoryConflictError",
    "MemoryDraftField",
    "MemoryDraftValidation",
    "MemoryGeneratedNoteError",
    "MemoryMutationError",
    "MemoryMutationOutcome",
    "MemoryNoteDraft",
    "MemoryScopeKind",
    "MemoryValidationError",
    "create_memory_note",
    "delete_memory_note",
    "memory_note_digest",
    "memory_note_relative_path_for_stem",
    "update_memory_note",
    "validate_memory_note_draft",
]
