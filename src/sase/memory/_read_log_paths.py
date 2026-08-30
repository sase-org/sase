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
    raw_path = Path(memory_relative_path)
    if raw_path.is_absolute():
        raise MemoryReadPathError("memory read path must be relative to sase/memory/")

    parts = _normalize_memory_read_parts(raw_path)
    if not parts or parts == (".",):
        raise MemoryReadPathError("memory read path is required")
    if any(part in {"", ".", ".."} for part in parts):
        raise MemoryReadPathError("memory read path must not contain traversal")
    if Path(*parts).suffix != ".md":
        raise MemoryReadPathError("memory read path must point to a .md file")
    if not _is_flat_note_path(parts):
        raise MemoryReadPathError("memory read path must be a flat .md note name")

    for content_root, memory_root in _memory_read_roots(project_root, home_root):
        path = _validate_memory_read_candidate(
            content_root=content_root,
            memory_root=memory_root,
            parts=parts,
            raw_path=raw_path,
        )
        if path is not None:
            return path

    raise MemoryReadPathError(f"memory file does not exist: {raw_path.as_posix()}")


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
            raise MemoryReadPathError(str(exc)) from exc
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
    allowed_root = memory_root.resolve(strict=False)
    candidate = memory_root.joinpath(*parts)

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        if _has_broken_symlink_component(candidate, memory_root):
            raise MemoryReadPathError(
                f"memory file cannot be resolved: {raw_path.as_posix()}"
            ) from exc
        return None
    except OSError as exc:
        raise MemoryReadPathError(
            f"memory file cannot be resolved: {raw_path.as_posix()}"
        ) from exc

    if not candidate.is_file():
        raise MemoryReadPathError(f"memory path is not a file: {raw_path.as_posix()}")
    if not _is_relative_to(resolved, allowed_root):
        raise MemoryReadPathError(
            "memory file resolves outside the allowed sase/memory/ directory"
        )

    note = _read_validated_memory_note(
        memory_root=memory_root,
        path=candidate,
        raw_path=raw_path,
    )
    if note.is_web_descriptor:
        slug = Path(note.relative_path).stem
        raise MemoryReadPathError(
            f"{note.relative_path} is an always-loaded memory web descriptor; "
            f"read its strands with `sase memory read {slug}:<keyword>`"
        )
    if note.type == "core":
        raise MemoryReadPathError(
            f"{note.relative_path} is always-loaded context and cannot be read with this command"
        )
    if note.type != "reference":
        raise MemoryReadPathError(
            f"memory file is not a reference memory note: {note.relative_path}"
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
        raise MemoryReadPathError(
            f"memory file does not exist: {raw_path.as_posix()}"
        ) from exc
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
