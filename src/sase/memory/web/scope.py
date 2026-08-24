"""Project-over-home memory-web scope merging."""

from __future__ import annotations

from .lookup import normalize_memory_web_reference
from .models import (
    MemoryStrand,
    MemoryWeb,
    ScopedMemoryWeb,
    WebScope,
    WebStrandOrigin,
)


def merge_memory_web_scopes(
    *,
    project_webs: tuple[MemoryWeb, ...] = (),
    home_webs: tuple[MemoryWeb, ...] = (),
) -> tuple[ScopedMemoryWeb, ...]:
    """Merge home and project webs per strand, with project strands winning."""

    home_by_slug = {web.slug: web for web in home_webs}
    project_by_slug = {web.slug: web for web in project_webs}
    merged: list[ScopedMemoryWeb] = []
    for slug in sorted(set(home_by_slug) | set(project_by_slug)):
        web = project_by_slug.get(slug) or home_by_slug[slug]
        origins: dict[str, WebStrandOrigin] = {}
        sources: tuple[tuple[WebScope, MemoryWeb | None], ...] = (
            ("home", home_by_slug.get(slug)),
            ("project", project_by_slug.get(slug)),
        )
        for scope, source in sources:
            if source is None:
                continue
            for strand in source.strands:
                origins[strand.slug] = WebStrandOrigin(
                    scope=scope,
                    strand=strand,
                )
        strands = tuple(
            origins[item].strand
            for item in sorted(
                origins,
                key=lambda strand_slug: normalize_memory_web_reference(
                    origins[strand_slug].strand.keyword
                ),
            )
        )
        merged.append(
            ScopedMemoryWeb(
                slug=slug,
                web=web,
                strands=strands,
                origins=origins,
            )
        )
    return tuple(merged)


def _strand_labels(strand: MemoryStrand) -> tuple[str, ...]:
    """Return normalized keyword and alias labels for cross-scope comparison."""

    return tuple(
        label
        for label in (
            normalize_memory_web_reference(value)
            for value in (strand.keyword, *strand.aliases)
        )
        if label
    )


def cross_scope_keyword_warnings(
    *,
    project_webs: tuple[MemoryWeb, ...] = (),
    home_webs: tuple[MemoryWeb, ...] = (),
) -> tuple[str, ...]:
    """Return non-blocking project/home keyword collision warnings."""

    project_by_slug = {web.slug: web for web in project_webs}
    home_by_slug = {web.slug: web for web in home_webs}
    warnings: list[str] = []
    for slug in sorted(set(project_by_slug) & set(home_by_slug)):
        project_web = project_by_slug[slug]
        home_web = home_by_slug[slug]
        home_labels: dict[str, str] = {}
        for strand in home_web.strands:
            for label in _strand_labels(strand):
                home_labels.setdefault(label, strand.keyword)
        for strand in project_web.strands:
            for label in _strand_labels(strand):
                home_keyword = home_labels.get(label)
                if home_keyword is None:
                    continue
                warnings.append(
                    f"memory web {slug}: project strand {strand.keyword!r} "
                    f"collides with home strand {home_keyword!r}; project wins"
                )
                break
    return tuple(warnings)


__all__ = [
    "cross_scope_keyword_warnings",
    "merge_memory_web_scopes",
]
