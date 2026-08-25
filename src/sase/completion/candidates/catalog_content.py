"""Catalog fetchers for project memory selectors.

Fetchers read through the project's resolved content layout; see
:mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

from pathlib import Path

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate

_CANONICAL_MEMORY_RELATIVE_ROOT = Path("sase") / "memory"
_LEGACY_MEMORY_RELATIVE_ROOT = Path("memory")
_README_FILENAME = "README.md"


def _project_root(project: str | None) -> Path | None:
    """Return the project root for *project*, or the current one."""

    if project is None:
        try:
            return Path.cwd()
        except OSError:
            return None
    from sase.completion.candidates.catalog_support import project_records_and_snapshot

    records, _snapshot = project_records_and_snapshot(project)
    for record in records:
        workspace_dir = (record.workspace_dir or "").strip()
        if workspace_dir:
            return Path(workspace_dir)
    return None


def memory_source_path(project: str | None) -> Path | None:
    """Return the memory directory whose mtime invalidates memory candidates."""
    root = _project_root(project)
    if root is None:
        return None
    roots = _memory_roots(root)
    return roots[0] if roots else None


def memory_candidates(project: str | None) -> list[Candidate]:
    """Return flat-note, web, and web-strand memory selectors."""

    root = _project_root(project)
    if root is None:
        return []
    candidates: list[Candidate] = []
    for memory_root in _memory_roots(root):
        for path in sorted(memory_root.glob("*.md")):
            if path.name == _README_FILENAME:
                continue
            candidates.append(Candidate(path.name, "memory note"))
        for web in _memory_web_candidates(memory_root):
            candidates.append(Candidate(web.slug, "memory web"))
            for strand in web.strands:
                description = strand.summary or f"{web.strand_noun} strand"
                candidates.append(Candidate(f"{web.slug}:{strand.slug}", description))
    return dedupe(candidates)


def _memory_roots(root: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for content_root in (root, Path.home()):
        if (
            content_root.resolve(strict=False) != root.resolve(strict=False)
            or not roots
        ):
            roots.extend(
                candidate
                for candidate in (
                    content_root / _CANONICAL_MEMORY_RELATIVE_ROOT,
                    content_root / _LEGACY_MEMORY_RELATIVE_ROOT,
                )
                if candidate.is_dir()
            )
    return tuple(dict.fromkeys(roots))


class _MemoryWebCandidate:
    def __init__(
        self,
        *,
        slug: str,
        strand_noun: str,
        strands: tuple[_MemoryStrandCandidate, ...],
    ) -> None:
        self.slug = slug
        self.strand_noun = strand_noun
        self.strands = strands


class _MemoryStrandCandidate:
    def __init__(self, *, slug: str, summary: str | None) -> None:
        self.slug = slug
        self.summary = summary


def _memory_web_candidates(memory_root: Path) -> tuple[_MemoryWebCandidate, ...]:
    webs: list[_MemoryWebCandidate] = []
    for descriptor in sorted(memory_root.glob("*.md")):
        if descriptor.name == _README_FILENAME:
            continue
        frontmatter = _frontmatter(descriptor)
        if not _is_true(frontmatter.get("web")):
            continue
        slug = descriptor.stem
        strand_noun = frontmatter.get("strand_noun") or "strand"
        strands: list[_MemoryStrandCandidate] = []
        strand_dir = memory_root / slug
        if strand_dir.is_dir():
            for strand_path in sorted(strand_dir.glob("*.md")):
                strand_frontmatter = _frontmatter(strand_path)
                strands.append(
                    _MemoryStrandCandidate(
                        slug=strand_path.stem,
                        summary=strand_frontmatter.get("summary"),
                    )
                )
        webs.append(
            _MemoryWebCandidate(
                slug=slug,
                strand_noun=strand_noun,
                strands=tuple(strands),
            )
        )
    return tuple(webs)


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if not separator or key.startswith((" ", "\t")):
            continue
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        values[key] = _unquote(value)
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _is_true(value: str | None) -> bool:
    return value is not None and value.casefold() == "true"


__all__ = [
    "memory_candidates",
    "memory_source_path",
]
