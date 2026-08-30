"""Provider-backed discovery for file memory webs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol

from sase.memory.paths import memory_read_root

from .frontmatter import parse_memory_strand, parse_web_descriptor
from .models import (
    MemoryStrand,
    MemoryWeb,
    MemoryWebDiscovery,
    MemoryWebDiscoveryIssue,
)

_IGNORED_ROOT_DIRECTORIES = frozenset({"assets"})


class MemoryWebProvider(Protocol):
    """Discovery provider interface for memory webs."""

    def discover(
        self,
        root: Path,
        *,
        source_memory_root: Path | None = None,
    ) -> MemoryWebDiscovery:
        """Return discovered webs and fail-closed discovery issues."""


class FileMemoryWebProvider:
    """Discover user-owned descriptor and strand files from a memory root."""

    def discover(
        self,
        root: Path,
        *,
        source_memory_root: Path | None = None,
    ) -> MemoryWebDiscovery:
        root_resolved = root.resolve(strict=False)
        memory_root = (
            source_memory_root.resolve(strict=False)
            if source_memory_root is not None
            else memory_read_root(root_resolved)
        )
        if memory_root is None or not memory_root.exists():
            return MemoryWebDiscovery(
                root=root_resolved,
                memory_root=memory_root,
                webs=(),
            )

        issues: list[MemoryWebDiscoveryIssue] = []
        web_by_slug: dict[str, MemoryWeb] = {}
        descriptor_state: dict[str, bool] = {}

        for descriptor_path in sorted(memory_root.glob("*.md")):
            if descriptor_path.name == "README.md":
                continue
            _record_symlink_escape(issues, memory_root, descriptor_path)
            web, error = parse_web_descriptor(
                root=root_resolved,
                memory_root=memory_root,
                path=descriptor_path,
            )
            if error is not None:
                issues.append(_issue("frontmatter", descriptor_path, error))
                descriptor_state[descriptor_path.stem] = False
                continue
            descriptor_state[descriptor_path.stem] = web is not None
            if web is not None:
                web_by_slug[web.slug] = web

        for web in tuple(web_by_slug.values()):
            strand_dir = memory_root / web.slug
            if strand_dir.exists() and strand_dir.is_dir():
                strands = _discover_strands(
                    root_resolved,
                    memory_root,
                    web,
                    strand_dir,
                    issues,
                )
                web_by_slug[web.slug] = replace(web, strands=strands)

        for directory in sorted(
            path for path in memory_root.iterdir() if path.is_dir()
        ):
            if directory.name in _IGNORED_ROOT_DIRECTORIES:
                _record_symlink_escape(issues, memory_root, directory)
                continue
            _record_symlink_escape(issues, memory_root, directory)
            state = descriptor_state.get(directory.name)
            if state is True:
                continue
            if state is False:
                message = (
                    f"{directory}: strand directory sibling "
                    f"{directory.name}.md does not declare web: true"
                )
            else:
                message = f"{directory}: strand directory has no descriptor note"
            issues.append(_issue("directory", directory, message))

        return MemoryWebDiscovery(
            root=root_resolved,
            memory_root=memory_root,
            webs=tuple(sorted(web_by_slug.values(), key=lambda item: item.slug)),
            issues=tuple(issues),
        )


def _discover_strands(
    root: Path,
    memory_root: Path,
    web: MemoryWeb,
    strand_dir: Path,
    issues: list[MemoryWebDiscoveryIssue],
) -> tuple[MemoryStrand, ...]:
    strands: list[MemoryStrand] = []
    for child in sorted(strand_dir.iterdir()):
        _record_symlink_escape(issues, memory_root, child)
        if child.is_dir():
            issues.append(
                _issue(
                    "nested_directory",
                    child,
                    f"{child}: nested directories are not allowed in memory webs",
                )
            )
            continue
        if child.suffix != ".md" or not child.is_file():
            continue
        strand, error = parse_memory_strand(
            root=root,
            memory_root=memory_root,
            web_slug=web.slug,
            path=child,
            link_reference=web.link_reference,
            link_rendering=web.link_rendering,
        )
        if error is not None:
            issues.append(_issue("frontmatter", child, error))
            continue
        if strand is not None:
            strands.append(strand)
    return tuple(sorted(strands, key=lambda item: item.slug))


def _record_symlink_escape(
    issues: list[MemoryWebDiscoveryIssue],
    memory_root: Path,
    path: Path,
) -> None:
    if not path.is_symlink():
        return
    root_resolved = memory_root.resolve(strict=False)
    target = path.resolve(strict=False)
    try:
        target.relative_to(root_resolved)
    except ValueError:
        issues.append(
            _issue(
                "symlink_escape",
                path,
                f"{path}: symlink resolves outside the memory root",
            )
        )


def _issue(code: str, path: Path, message: str) -> MemoryWebDiscoveryIssue:
    return MemoryWebDiscoveryIssue(code=code, path=path, message=message)


def discover_memory_webs(
    root: Path,
    *,
    source_memory_root: Path | None = None,
    provider: MemoryWebProvider | None = None,
) -> MemoryWebDiscovery:
    """Discover memory webs from *root* using *provider* or the file provider."""

    resolved_provider = provider or FileMemoryWebProvider()
    return resolved_provider.discover(root, source_memory_root=source_memory_root)


__all__ = [
    "FileMemoryWebProvider",
    "MemoryWebProvider",
    "discover_memory_webs",
]
