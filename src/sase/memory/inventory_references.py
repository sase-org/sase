"""Reference parsing and path resolution for memory inventories."""

from __future__ import annotations

from collections.abc import Mapping
from math import ceil
from pathlib import Path
import re

from sase.memory.inventory_models import (
    INSTRUCTION_ROOT_FILENAMES,
    LOADED_INSTRUCTION_ROOT_FILENAMES,
    MemoryContextRoot,
    MemoryStats,
    ParsedMemoryReference,
    ResolvedReference,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    memory_note_relative_path,
    memory_read_root,
)

_AT_REF_RE = re.compile(r"(?:^|(?<=\s)|(?<=[\"'`(]))@([^\s,;:()[\]{}\"'`]+)")
_MEMORY_PATH_RE = re.compile(
    r"(?<![\w./-])((?:sase/)?memory/[^\s,;:()[\]{}\"'`/]+?\.md)"
)
_TRAILING_TOKEN_PUNCTUATION = ".,;:!?)"


def normalize_overlay(overlay: Mapping[Path, str] | None) -> dict[Path, str]:
    if overlay is None:
        return {}
    return {path.resolve(strict=False): content for path, content in overlay.items()}


def path_exists(path: Path, overlay: Mapping[Path, str]) -> bool:
    return path.resolve(strict=False) in overlay or path.is_file()


def read_text(path: Path, overlay: Mapping[Path, str]) -> str | None:
    resolved = path.resolve(strict=False)
    if resolved in overlay:
        return overlay[resolved]
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _clean_token(token: str) -> str:
    return token.rstrip(_TRAILING_TOKEN_PUNCTUATION)


def _overlaps(span: tuple[int, int], spans: tuple[tuple[int, int], ...]) -> bool:
    start, end = span
    return any(
        start < other_end and other_start < end for other_start, other_end in spans
    )


def _parse_references(text: str) -> tuple[ParsedMemoryReference, ...]:
    """Return typed reference tokens found in ``text``.

    ``@memory/foo.md`` is reported only as a loaded reference, not also as a
    plain memory-path mention.
    """
    references: list[tuple[int, ParsedMemoryReference]] = []
    loaded_spans: list[tuple[int, int]] = []
    for match in _AT_REF_RE.finditer(text):
        token = _clean_token(match.group(1))
        if not token:
            continue
        loaded_spans.append(match.span(1))
        references.append(
            (match.start(1), ParsedMemoryReference(kind="loaded", token=token))
        )

    loaded_span_tuple = tuple(loaded_spans)
    for match in _MEMORY_PATH_RE.finditer(text):
        if _overlaps(match.span(1), loaded_span_tuple):
            continue
        token = _clean_token(match.group(1))
        if not token:
            continue
        references.append(
            (match.start(1), ParsedMemoryReference(kind="plain", token=token))
        )

    return tuple(
        reference for _, reference in sorted(references, key=lambda item: item[0])
    )


def _inside_root(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def is_memory_path(root: Path, path: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        root_relative = path.relative_to(root)
    except ValueError:
        return False
    relative = memory_note_relative_path(root_relative)
    if relative is None:
        return False
    return len(relative.parts) == 1 and relative.name != "README.md"


def iter_memory_files(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    overlay_files = normalize_overlay(overlay)
    memory_root = (
        source_memory_root.resolve(strict=False)
        if source_memory_root is not None
        else memory_read_root(root_resolved)
    )
    results: list[Path] = []
    if memory_root is not None and memory_root.exists():
        results.extend(
            path.resolve(strict=False)
            for path in memory_root.glob("*.md")
            if path.is_file() and path.name != "README.md"
        )
    results.extend(
        path
        for path in overlay_files
        if _inside_root(root_resolved, path) and is_memory_path(root_resolved, path)
    )
    canonical_overlay_names = {
        path.name
        for path in overlay_files
        if path.parent == root_resolved / CANONICAL_MEMORY_RELATIVE_ROOT
    }
    results = [
        path
        for path in results
        if not (
            path.parent == root_resolved / "memory"
            and path.name in canonical_overlay_names
        )
    ]
    return tuple(sorted(set(results), key=lambda path: path.as_posix()))


def instruction_roots(root: Path) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    roots: list[Path] = []
    for filename in INSTRUCTION_ROOT_FILENAMES:
        path = (root_resolved / filename).resolve(strict=False)
        if path.is_file():
            roots.append(path)
    return tuple(roots)


def loaded_instruction_roots(root: Path) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    roots: list[Path] = []
    for filename in LOADED_INSTRUCTION_ROOT_FILENAMES:
        path = (root_resolved / filename).resolve(strict=False)
        if path.is_file():
            roots.append(path)
    return tuple(roots)


def context_roots(
    project_root: Path, home_root: Path | None
) -> tuple[MemoryContextRoot, ...]:
    project_root_resolved = project_root.resolve(strict=False)
    roots = [
        MemoryContextRoot(root=project_root_resolved, kind="project"),
    ]
    if home_root is None:
        return tuple(roots)

    home_root_resolved = home_root.expanduser().resolve(strict=False)
    if home_root_resolved != project_root_resolved:
        roots.append(MemoryContextRoot(root=home_root_resolved, kind="home"))
    return tuple(roots)


def _candidate_paths(root: Path, source: Path, token: str) -> tuple[Path, ...]:
    expanded = Path(token).expanduser()
    if expanded.is_absolute():
        return (expanded,)

    if token.startswith(("./", "../")):
        return (source.parent / expanded,)
    return (root / expanded, source.parent / expanded)


def display_path_for_context(
    context_roots: tuple[MemoryContextRoot, ...], path: Path
) -> str:
    """Return the user-facing path for ``path`` within an inventory."""
    resolved = path.resolve(strict=False)
    for context_root in context_roots:
        try:
            relative = resolved.relative_to(context_root.root)
        except ValueError:
            continue

        relative_text = relative.as_posix()
        if relative_text == ".":
            return "~" if context_root.kind == "home" else "."
        if context_root.kind == "home":
            return f"~/{relative_text}"
        return relative_text
    return resolved.as_posix()


def resolve_reference(
    root: Path,
    source: Path,
    token: str,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> ResolvedReference | None:
    """Resolve ``token`` using init-memory root containment rules."""
    if token.startswith(("http://", "https://")):
        return None

    overlay_files = normalize_overlay(overlay)
    root_resolved = root.resolve(strict=False)
    source_resolved = source.resolve(strict=False)
    in_root_candidates: list[Path] = []
    candidates = list(_candidate_paths(root_resolved, source_resolved, token))
    memory_relative = memory_note_relative_path(Path(token))
    if memory_relative is not None:
        selected_memory_root = source_memory_root or memory_read_root(root_resolved)
        if selected_memory_root is not None:
            candidates.insert(1, selected_memory_root / memory_relative)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if not _inside_root(root_resolved, resolved):
            continue
        if path_exists(resolved, overlay_files):
            return ResolvedReference(target=resolved, exists=True)
        in_root_candidates.append(resolved)

    if not in_root_candidates:
        return None
    return ResolvedReference(target=in_root_candidates[0], exists=False)


def references_from_file(
    root: Path,
    source: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[tuple[ParsedMemoryReference, ResolvedReference], ...]:
    overlay_files = normalize_overlay(overlay)
    text = read_text(source, overlay_files)
    if text is None:
        return ()

    resolved: list[tuple[ParsedMemoryReference, ResolvedReference]] = []
    for parsed in _parse_references(text):
        target = resolve_reference(
            root,
            source,
            parsed.token,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
        if target is None:
            continue
        resolved.append((parsed, target))
    return tuple(resolved)


def stats_for_text(text: str) -> MemoryStats:
    return MemoryStats(
        line_count=len(text.splitlines()),
        approx_token_count=ceil(len(text) / 4) if text else 0,
    )


def stats_for_file(path: Path) -> MemoryStats | None:
    try:
        return stats_for_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None
