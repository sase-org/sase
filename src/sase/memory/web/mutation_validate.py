"""Pure validation for memory-web strand create drafts.

This module does not read or write the filesystem. Callers pass the target
web's already-discovered strands so a form can share them with the engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re
from typing import Any

from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.memory.web.frontmatter import slug_to_keyword
from sase.memory.web.lookup import MemoryWebLookupError, resolve_memory_strand
from sase.memory.web.models import MemoryWeb
from sase.memory.web.mutation_models import (
    MemoryStrandDraft,
    MemoryStrandDraftField,
    MemoryStrandDraftValidation,
)

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate_memory_strand_draft(
    *,
    web: MemoryWeb,
    slug: str,
    keyword: str | None = None,
    aliases: Sequence[str] = (),
    summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MemoryStrandDraftValidation:
    """Return per-field diagnostics for a strand create draft.

    This function is pure: it does not read or write the filesystem. Callers
    pass the target web's already-discovered strands (``web.strands``) so a
    panel form can share them.
    """
    errors: dict[MemoryStrandDraftField, list[str]] = {
        "slug": [],
        "keyword": [],
        "aliases": [],
        "summary": [],
        "metadata": [],
    }

    parsed_slug, slug_errors = _parse_slug(slug)
    errors["slug"].extend(slug_errors)

    parsed_keyword, keyword_errors = _parse_keyword(keyword, fallback_slug=parsed_slug)
    errors["keyword"].extend(keyword_errors)

    parsed_aliases, alias_errors = _parse_aliases(aliases)
    errors["aliases"].extend(alias_errors)

    parsed_summary, summary_errors = _parse_summary(summary)
    errors["summary"].extend(summary_errors)

    parsed_metadata, metadata_errors = _parse_metadata(metadata)
    errors["metadata"].extend(metadata_errors)

    if parsed_slug is not None and _resolves_in_web(web, parsed_slug):
        errors["slug"].append(
            f"a memory strand already exists at {parsed_slug} in {web.slug}"
        )
    if parsed_keyword is not None and _resolves_in_web(web, parsed_keyword):
        errors["keyword"].append(
            f"memory strand keyword collides with an existing strand in "
            f"{web.slug}: {parsed_keyword}"
        )
    for alias in parsed_aliases:
        if _resolves_in_web(web, alias):
            errors["aliases"].append(
                f"memory strand alias collides with an existing strand in "
                f"{web.slug}: {alias}"
            )

    draft: MemoryStrandDraft | None = None
    if parsed_slug is not None and parsed_keyword is not None:
        draft = MemoryStrandDraft(
            slug=parsed_slug,
            relative_path=(
                CANONICAL_MEMORY_RELATIVE_ROOT / web.slug / f"{parsed_slug}.md"
            ).as_posix(),
            keyword=parsed_keyword,
            aliases=parsed_aliases,
            summary=parsed_summary,
            metadata=parsed_metadata,
        )

    by_field = {
        field: tuple(messages) for field, messages in errors.items() if messages
    }
    return MemoryStrandDraftValidation(draft=draft, by_field=by_field)


def _resolves_in_web(web: MemoryWeb, reference: str) -> bool:
    try:
        resolve_memory_strand(web, reference)
    except MemoryWebLookupError:
        return False
    return True


def _normalized_scalar(value: str) -> str | None:
    normalized = " ".join(value.split())
    return normalized or None


def _parse_slug(raw: str) -> tuple[str | None, tuple[str, ...]]:
    cleaned = raw.strip()
    if cleaned.lower().endswith(".md"):
        cleaned = cleaned[:-3]
    if not cleaned:
        return None, ("memory strand slug is required",)
    path = Path(cleaned.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None, (
            "memory strand slug must be a single flat segment without traversal",
        )
    if len(path.parts) != 1:
        return None, ("memory strand slug must be a single flat segment",)
    if not _SLUG_RE.fullmatch(cleaned):
        return None, ("memory strand slug must match [A-Za-z0-9][A-Za-z0-9_-]*",)
    return cleaned, ()


def _parse_keyword(
    keyword: str | None, *, fallback_slug: str | None
) -> tuple[str | None, tuple[str, ...]]:
    if keyword is None:
        if fallback_slug is None:
            return None, ()
        return slug_to_keyword(fallback_slug), ()
    cleaned = _normalized_scalar(keyword)
    if cleaned is None:
        return None, ("memory strand keyword must be a non-empty string",)
    return cleaned, ()


def _parse_aliases(aliases: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    errors: list[str] = []
    parsed: list[str] = []
    seen: dict[str, str] = {}
    for raw in aliases:
        cleaned = _normalized_scalar(raw) if isinstance(raw, str) else None
        if cleaned is None:
            errors.append("memory strand aliases must be non-empty strings")
            continue
        key = cleaned.casefold()
        if key in seen:
            errors.append(f"duplicate memory strand alias: {cleaned}")
            continue
        seen[key] = cleaned
        parsed.append(cleaned)
    return tuple(parsed), tuple(errors)


def _parse_summary(summary: str | None) -> tuple[str | None, tuple[str, ...]]:
    if summary is None:
        return None, ()
    cleaned = _normalized_scalar(summary)
    if cleaned is None:
        return None, ("memory strand summary must be a non-empty string",)
    return cleaned, ()


def _parse_metadata(
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if metadata is None:
        return {}, ()
    if not isinstance(metadata, Mapping):
        return {}, ("memory strand metadata must be a mapping",)
    if not all(isinstance(key, str) for key in metadata):
        return {}, ("memory strand metadata keys must be strings",)
    return dict(metadata), ()


__all__ = ["validate_memory_strand_draft"]
