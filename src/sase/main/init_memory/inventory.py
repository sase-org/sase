"""Memory reference discovery and validation helpers."""

from __future__ import annotations

from pathlib import Path
import re
import sys

from .constants import COMMAND_LABEL
from .models import MemoryRootResult

_AT_REF_RE = re.compile(r"(?:^|(?<=\s)|(?<=[\"'`(]))@([^\s,;:()[\]{}\"'`]+)")
_MEMORY_PATH_RE = re.compile(
    r"(?<![\w./-])(memory/(?:short|long)/[^\s,;:()[\]{}\"'`]+?\.md)"
)


def _memory_files(root: Path) -> set[Path]:
    memory_root = root / "memory"
    results: set[Path] = set()
    for tier in ("short", "long"):
        tier_root = memory_root / tier
        if not tier_root.exists():
            continue
        results.update(
            path.resolve(strict=False)
            for path in tier_root.rglob("*.md")
            if path.is_file()
        )
    return results


def _extract_reference_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _AT_REF_RE.finditer(text):
        token = match.group(1).rstrip(".,;:!?)")
        if token:
            tokens.append(token)
    for match in _MEMORY_PATH_RE.finditer(text):
        token = match.group(1).rstrip(".,;:!?)")
        if token:
            tokens.append(token)
    return tokens


def _resolve_reference(root: Path, source: Path, token: str) -> Path | None:
    if token.startswith(("http://", "https://")):
        return None

    expanded = Path(token).expanduser()
    candidates: list[Path]
    if expanded.is_absolute():
        candidates = [expanded]
    elif token.startswith(("./", "../")):
        candidates = [source.parent / expanded]
    else:
        candidates = [root / expanded, source.parent / expanded]

    root_resolved = root.resolve(strict=False)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _referenced_files_from(root: Path, source: Path) -> set[Path]:
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return set()

    refs: set[Path] = set()
    for token in _extract_reference_tokens(text):
        resolved = _resolve_reference(root, source, token)
        if resolved is not None:
            refs.add(resolved)
    return refs


def _reachable_memory_files(root: Path) -> set[Path]:
    agents_path = (root / "AGENTS.md").resolve(strict=False)
    if not agents_path.exists():
        return set()

    memory_files = _memory_files(root)
    reachable: set[Path] = set()
    visited: set[Path] = {agents_path}
    queue = list(_referenced_files_from(root, agents_path))

    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        if path in memory_files:
            reachable.add(path)
            queue.extend(_referenced_files_from(root, path))

    return reachable


def unreferenced_memory_files(root: Path) -> tuple[Path, ...]:
    memory_files = _memory_files(root)
    reachable = _reachable_memory_files(root)
    return tuple(sorted(memory_files - reachable, key=lambda path: path.as_posix()))


def print_validation_errors(results: tuple[MemoryRootResult, ...]) -> None:
    printed = False
    for result in results:
        if not result.unreferenced:
            continue
        if not printed:
            print(
                f"{COMMAND_LABEL}: unreferenced memory files were found",
                file=sys.stderr,
            )
            printed = True
        print(f"  {result.root}:", file=sys.stderr)
        for path in result.unreferenced:
            try:
                display = path.relative_to(result.root.resolve(strict=False))
            except ValueError:
                display = path
            print(f"    - {display}", file=sys.stderr)
