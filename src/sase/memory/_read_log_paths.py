"""Path validation and content loading for audited memory reads."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.content_layout import LayoutCollisionError
from sase.memory._read_log_models import (
    FrontmatterStripResult,
    MemoryReadContent,
    MemoryReadPathError,
    ValidatedMemoryPath,
)
from sase.memory.notes import MemoryNote, parse_memory_note_text
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    LEGACY_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_read_root,
)


def validate_memory_read_path(
    memory_relative_path: str | Path,
    *,
    project_root: Path | None = None,
    home_root: Path | None = None,
) -> ValidatedMemoryPath:
    """Validate and canonicalize a path relative to an allowed memory root."""

    def _path_error(message: str, reason: str) -> MemoryReadPathError:
        exc = MemoryReadPathError(message)
        try:
            exc.reason = reason  # type: ignore[attr-defined]
        except Exception:
            pass
        return exc

    raw_path = Path(memory_relative_path)
    if raw_path.is_absolute():
        raise _path_error(
            "memory read path must be relative to sase/memory/", "invalid_syntax"
        )

    parts = _normalize_memory_read_parts(raw_path)
    if not parts or parts == (".",):
        raise _path_error("memory read path is required", "invalid_syntax")
    if any(part in {"", ".", ".."} for part in parts):
        raise _path_error("memory read path must not contain traversal", "traversal")
    if Path(*parts).suffix != ".md":
        raise _path_error("memory read path must point to a .md file", "invalid_syntax")
    if not _is_flat_note_path(parts):
        raise _path_error(
            "memory read path must be a flat .md note name", "invalid_syntax"
        )

    for content_root, memory_root in _memory_read_roots(project_root, home_root):
        path = _validate_memory_read_candidate(
            content_root=content_root,
            memory_root=memory_root,
            parts=parts,
            raw_path=raw_path,
        )
        if path is not None:
            return path

    raise _path_error(f"memory file does not exist: {raw_path.as_posix()}", "missing")


def _normalize_memory_read_parts(raw_path: Path) -> tuple[str, ...]:
    parts = raw_path.parts
    for prefix in (
        CANONICAL_MEMORY_RELATIVE_ROOT.parts,
        LEGACY_MEMORY_RELATIVE_ROOT.parts,
    ):
        if parts[: len(prefix)] == prefix:
            return parts[len(prefix) :]
    return parts


def _is_flat_note_path(parts: tuple[str, ...]) -> bool:
    return len(parts) == 1


def _memory_read_roots(
    project_root: Path | None,
    home_root: Path | None,
) -> tuple[tuple[Path, Path], ...]:
    root = (project_root or Path.cwd()).resolve(strict=False)
    content_roots = [root]

    if home_root is not None:
        resolved_home_root = home_root.expanduser().resolve(strict=False)
        if resolved_home_root != root:
            content_roots.append(resolved_home_root)

    roots: list[tuple[Path, Path]] = []
    for content_root in content_roots:
        try:
            selected = memory_read_root(
                content_root,
                label=f"memory for {content_root}",
            )
        except LayoutCollisionError as exc:
            collision = MemoryReadPathError(str(exc))
            try:
                collision.reason = "collision"  # type: ignore[attr-defined]
            except Exception:
                pass
            raise collision from exc
        if selected is not None:
            roots.append((content_root, selected))
    return tuple(roots)


def _validate_memory_read_candidate(
    *,
    content_root: Path,
    memory_root: Path,
    parts: tuple[str, ...],
    raw_path: Path,
) -> ValidatedMemoryPath | None:
    def _candidate_error(message: str, reason: str) -> MemoryReadPathError:
        exc = MemoryReadPathError(message)
        try:
            exc.reason = reason  # type: ignore[attr-defined]
        except Exception:
            pass
        return exc

    allowed_root = memory_root.resolve(strict=False)
    candidate = memory_root.joinpath(*parts)

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        if _has_broken_symlink_component(candidate, memory_root):
            raise _candidate_error(
                f"memory file cannot be resolved: {raw_path.as_posix()}",
                "symlink",
            ) from exc
        return None
    except OSError as exc:
        raise _candidate_error(
            f"memory file cannot be resolved: {raw_path.as_posix()}", "unreadable"
        ) from exc

    if not candidate.is_file():
        raise _candidate_error(
            f"memory path is not a file: {raw_path.as_posix()}", "not_file"
        )
    if not _is_relative_to(resolved, allowed_root):
        raise _candidate_error(
            "memory file resolves outside the allowed sase/memory/ directory",
            "escape",
        )

    note = _read_validated_memory_note(
        memory_root=memory_root,
        path=candidate,
        raw_path=raw_path,
    )
    if note.is_web_descriptor:
        slug = Path(note.relative_path).stem
        raise _candidate_error(
            f"{note.relative_path} is an always-loaded memory web descriptor; "
            f"read its strands with `sase memory read {slug}:<keyword>`",
            "note_kind",
        )
    if note.type == "core":
        raise _candidate_error(
            f"{note.relative_path} is always-loaded context and cannot be read with this command",
            "note_kind",
        )
    if note.type != "reference":
        raise _candidate_error(
            f"memory file is not a reference memory note: {note.relative_path}",
            "note_kind",
        )

    canonical_path = Path(*parts).as_posix()
    return ValidatedMemoryPath(
        memory_root=memory_root,
        allowed_root=allowed_root,
        canonical_path=canonical_path,
        path=candidate,
        resolved_path=resolved,
        note=note,
        content_root=content_root,
    )


def _read_validated_memory_note(
    *,
    memory_root: Path,
    path: Path,
    raw_path: Path,
) -> MemoryNote:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        missing = MemoryReadPathError(
            f"memory file does not exist: {raw_path.as_posix()}"
        )
        try:
            missing.reason = "missing"  # type: ignore[attr-defined]
        except Exception:
            pass
        raise missing from exc
    except OSError as exc:
        unreadable = MemoryReadPathError(
            f"memory file cannot be read: {raw_path.as_posix()}"
        )
        try:
            unreadable.reason = "unreadable"  # type: ignore[attr-defined]
        except Exception:
            pass
        raise unreadable from exc
    relative = path.relative_to(memory_root)
    note = parse_memory_note_text(
        text,
        CANONICAL_MEMORY_RELATIVE_ROOT / relative,
    )
    return replace(
        note,
        parent=canonical_memory_reference(note.parent).as_posix(),
        source_path=None,
    )


def _has_broken_symlink_component(path: Path, root: Path) -> bool:
    current = root
    components = [current]
    for part in path.relative_to(root).parts:
        current = current / part
        components.append(current)

    for component in components:
        if not component.is_symlink():
            continue
        try:
            component.resolve(strict=True)
        except (FileNotFoundError, OSError, RuntimeError):
            return True
    return False


def read_memory_content(path: ValidatedMemoryPath) -> MemoryReadContent:
    """Read a validated memory file and strip leading YAML frontmatter."""
    raw_text = path.resolved_path.read_text(encoding="utf-8")
    stripped = strip_leading_frontmatter(raw_text)
    return MemoryReadContent(
        path=path,
        raw_text=raw_text,
        body=stripped.body,
        byte_count=len(raw_text.encode("utf-8")),
        frontmatter_stripped=stripped.stripped,
    )


def strip_leading_frontmatter(text: str) -> FrontmatterStripResult:
    """Remove one leading ``---`` frontmatter block, preserving body text."""
    lines = text.splitlines(keepends=True)
    if not lines or not _is_frontmatter_delimiter(lines[0]):
        return FrontmatterStripResult(body=text, stripped=False)

    for index, line in enumerate(lines[1:], start=1):
        if _is_frontmatter_delimiter(line):
            body_lines = lines[index + 1 :]
            if body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
            return FrontmatterStripResult(
                body="".join(body_lines),
                stripped=True,
            )
    return FrontmatterStripResult(body=text, stripped=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_frontmatter_delimiter(line: str) -> bool:
    return line.strip() == "---"


__all__ = [
    "read_memory_content",
    "strip_leading_frontmatter",
    "validate_memory_read_path",
]
