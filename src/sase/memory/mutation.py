"""CLI-free create/update/delete engine for SASE memory notes.

This module is the only code that writes memory notes. It has no Textual
import. Validation is pure; disk writes are atomic and digest-guarded.
"""

from __future__ import annotations

from collections.abc import Sequence
import errno
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from sase.content_layout import LayoutCollisionError
from sase.core.paths import sase_home
from sase.core.time import local_now
from sase.memory.mutation_models import (
    MemoryConflictError,
    MemoryDraftField,
    MemoryDraftValidation,
    MemoryGeneratedNoteError,
    MemoryMutationError,
    MemoryMutationOutcome,
    MemoryNoteDraft,
    MemoryScopeKind,
    MemoryValidationError,
)
from sase.memory.mutation_validate import (
    children_of_memory_note,
    memory_note_relative_path_for_stem,
    raise_if_generated_memory_note,
    raise_if_generated_memory_stem,
    require_flat_memory_note_path,
    validate_memory_note_draft,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    MemoryNoteType,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)
from sase.memory.paths import (
    memory_read_root,
    memory_write_root,
)

_BACKUP_DIRNAME = "memory-backups"


def memory_note_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of a memory note's on-disk bytes."""
    return hashlib.sha256(data).hexdigest()


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
    raise_if_generated_memory_stem(stem, include_project_memory)
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
    canonical = require_flat_memory_note_path(relative_path)
    raise_if_generated_memory_note(canonical, include_project_memory)
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
    canonical = require_flat_memory_note_path(relative_path)
    raise_if_generated_memory_note(canonical, include_project_memory)
    notes = _discover_notes(root)
    note = _require_existing_note(notes, canonical)
    children = children_of_memory_note(notes, canonical)
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
