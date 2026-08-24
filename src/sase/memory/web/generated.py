"""In-memory provider for SASE-generated memory webs (for example, task_types)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from sase.memory.paths import memory_write_root

from .frontmatter import parse_memory_strand, parse_web_descriptor
from .models import MemoryStrand, MemoryWebDiscovery


@dataclass(frozen=True)
class GeneratedStrandSource:
    """One generated strand's slug and fully rendered file content."""

    slug: str
    content: str


@dataclass(frozen=True)
class GeneratedWebSource:
    """A fully in-memory generated descriptor plus its strand sources."""

    slug: str
    descriptor_content: str
    strands: tuple[GeneratedStrandSource, ...]


class GeneratedMemoryWebProvider:
    """Discover one SASE-rendered web from in-memory content, not the filesystem.

    SASE owns the whole descriptor and every strand file for a generated web
    (``task_types`` today); the plugin registry that drives *source* is what
    controls which strand files ``sase memory init`` writes.
    """

    def __init__(self, source: GeneratedWebSource) -> None:
        self._source = source

    def discover(
        self,
        root: Path,
        *,
        source_memory_root: Path | None = None,
    ) -> MemoryWebDiscovery:
        """Discover the generated web, always rooted at the canonical write path.

        *source_memory_root* is accepted only for :class:`MemoryWebProvider`
        protocol conformance and ignored: unlike a file-backed web, a
        generated web has no pre-migration content to read, so it always
        targets ``memory_write_root(root)`` even mid-migration.
        """
        root_resolved = root.resolve(strict=False)
        memory_root = memory_write_root(root_resolved)

        descriptor_path = memory_root / f"{self._source.slug}.md"
        web, error = parse_web_descriptor(
            root=root_resolved,
            memory_root=memory_root,
            path=descriptor_path,
            text=self._source.descriptor_content,
            source="generated",
        )
        if error is not None or web is None:
            raise AssertionError(
                f"generated memory web {self._source.slug!r} failed to parse: {error}"
            )

        strand_dir = memory_root / self._source.slug
        strands: list[MemoryStrand] = []
        for strand_source in self._source.strands:
            strand, strand_error = parse_memory_strand(
                root=root_resolved,
                memory_root=memory_root,
                web_slug=self._source.slug,
                path=strand_dir / f"{strand_source.slug}.md",
                text=strand_source.content,
            )
            if strand_error is not None or strand is None:
                raise AssertionError(
                    f"generated memory strand {self._source.slug}:"
                    f"{strand_source.slug} failed to parse: {strand_error}"
                )
            strands.append(strand)

        web = replace(web, strands=tuple(sorted(strands, key=lambda item: item.slug)))
        return MemoryWebDiscovery(
            root=root_resolved,
            memory_root=memory_root,
            webs=(web,),
        )


__all__ = [
    "GeneratedMemoryWebProvider",
    "GeneratedStrandSource",
    "GeneratedWebSource",
]
