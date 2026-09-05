"""Load and unify prompt hits from the canonical archive and local history.

This read-only layer inventories ``prompts/<YYYYMM>/*.md`` in the agents
sidecar, adapts machine-wide prompt history into the same :class:`PromptHit`
shape, and collapses cross-store duplicates by content digest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sase.core.prompt_archive_facade import (
    PromptArchiveDocument,
    prompt_archive_inventory,
)
from sase.history.prompt import list_prompt_records
from sase.history.prompt_metadata import summarize_prompt_for_search
from sase.prompt.search.dates import resolve_archive_date
from sase.prompt.search.model import PromptHit, PromptSource
from sase.sdd.frontmatter import frontmatter_span, parse_frontmatter
from sase.sdd.plan_header_block import PlanHeaderSection, PlanHeaderSectionKind

_USER_TAGS_KEY = "prompt_tags"
_TAG_SIGILS = "#@"
_SEARCH_FRONTMATTER_KEYS = frozenset(
    {"sha256", "timestamp", "last_used", _USER_TAGS_KEY}
)


@dataclass(frozen=True, slots=True)
class _SearchTextMetadata:
    title: str
    tags: tuple[str, ...]


def collect_prompt_hits(
    sources: Iterable[PromptSource],
    archive_root: Path | None,
) -> list[PromptHit]:
    """Return the unified, de-duplicated corpus for the selected sources.

    Archive hits are listed before local hits. When both sources are selected,
    a local entry with the same ``text_sha256`` is collapsed into the archive
    hit and annotated with :attr:`PromptHit.also_in_local`.
    """

    selected = set(sources)
    archive_hits = (
        load_archive_prompt_hits(archive_root)
        if archive_root is not None and PromptSource.ARCHIVE in selected
        else []
    )
    local_hits = load_local_prompt_hits() if PromptSource.LOCAL in selected else []
    return _dedup_hits(archive_hits, local_hits)


def load_archive_prompt_hits(archive_root: Path) -> list[PromptHit]:
    """Load every canonical prompt in one agents-sidecar archive."""

    root = archive_root.expanduser().resolve(strict=False)
    hits: list[PromptHit] = []
    for document in prompt_archive_inventory(root):
        hit = _load_archive_document(document, root)
        if hit is not None:
            hits.append(hit)
    return hits


def _load_archive_document(
    document: PromptArchiveDocument,
    archive_root: Path,
) -> PromptHit | None:
    """Adapt one parsed archive document, tolerating an unreadable entry."""

    if document.parse_error is not None:
        return None

    content = document.content
    text = document.body.strip()
    frontmatter = _search_frontmatter(content)
    locator = document.name
    metadata = _derive_metadata(text, locator)
    plan = _section(document.sections, PlanHeaderSectionKind.PLAN)
    artifacts = _section(document.sections, PlanHeaderSectionKind.ARTIFACTS)
    recorded_sha = _str_or_none(frontmatter.get("sha256"))
    return PromptHit(
        source=PromptSource.ARCHIVE,
        id=locator,
        text=text,
        title=metadata.title,
        date=resolve_archive_date(frontmatter, document.path),
        text_sha256=recorded_sha or _sha256(text),
        path=_relative_path(document.path, archive_root),
        plan=plan.label if plan is not None else None,
        artifact_count=len(artifacts.entries) if artifacts is not None else 0,
        tags=_archive_tags(frontmatter, metadata.tags),
        cancelled=None,
        also_in_local=False,
    )


def load_local_prompt_hits() -> list[PromptHit]:
    """Adapt launched and cancelled machine-wide prompt history records."""

    return [
        _local_hit(record) for record in list_prompt_records(include_cancelled=True)
    ]


def _local_hit(record: Any) -> PromptHit:
    text = record.text
    metadata = _derive_metadata(text, record.id)
    return PromptHit(
        source=PromptSource.LOCAL,
        id=record.id,
        text=text,
        title=metadata.title,
        date=record.last_used,
        text_sha256=record.text_sha256,
        path=None,
        plan=None,
        artifact_count=None,
        tags=metadata.tags,
        cancelled=record.cancelled,
        also_in_local=False,
        render_record=record,
    )


def _dedup_hits(
    archive_hits: list[PromptHit],
    local_hits: list[PromptHit],
) -> list[PromptHit]:
    """Collapse same-digest local entries into their canonical archive hit."""

    archive_shas = {hit.text_sha256 for hit in archive_hits if hit.text_sha256}
    local_shas = {hit.text_sha256 for hit in local_hits if hit.text_sha256}

    result: list[PromptHit] = []
    for hit in archive_hits:
        result.append(
            replace(hit, also_in_local=True)
            if hit.text_sha256 and hit.text_sha256 in local_shas
            else hit
        )
    for hit in local_hits:
        if hit.text_sha256 and hit.text_sha256 in archive_shas:
            continue
        result.append(hit)
    return result


def _derive_metadata(text: str, fallback: str) -> _SearchTextMetadata:
    try:
        summary = summarize_prompt_for_search(text)
        title = summary.clean_preview
        tags = _dedup_tags(summary.xprompts)
    except Exception:
        title = " ".join(text.split())
        tags = ()
    return _SearchTextMetadata(title=title or fallback, tags=tags)


def _archive_tags(
    frontmatter: dict[str, Any],
    body_tags: tuple[str, ...],
) -> tuple[str, ...]:
    return _dedup_tags([*_frontmatter_tags(frontmatter), *body_tags])


def _search_frontmatter(content: str) -> dict[str, Any]:
    parsed = _simple_search_frontmatter(content)
    if parsed is not None:
        return parsed
    frontmatter, _, _ = parse_frontmatter(content)
    return frontmatter


def _simple_search_frontmatter(content: str) -> dict[str, Any] | None:
    """Parse the simple archive fields prompt search reads, or request fallback."""
    end = frontmatter_span(content)
    if end is None:
        return {}

    frontmatter: dict[str, Any] = {}
    lines = content[4:end].splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if raw_line[:1].isspace() or ":" not in raw_line:
            return None

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        if key not in _SEARCH_FRONTMATTER_KEYS:
            return None
        if key == _USER_TAGS_KEY:
            tags, index = _simple_prompt_tags(lines, index, raw_value)
            if tags is None:
                return None
            frontmatter[key] = tags
            continue

        value = _simple_yaml_scalar(raw_value)
        if value is None:
            return None
        frontmatter[key] = value
        index += 1
    return frontmatter


def _simple_prompt_tags(
    lines: list[str],
    index: int,
    raw_value: str,
) -> tuple[list[str] | str | None, int]:
    value = raw_value.strip()
    if value:
        if value.startswith("[") and value.endswith("]"):
            values = _simple_yaml_list(value[1:-1])
            return values, index + 1
        scalar = _simple_yaml_scalar(raw_value)
        return scalar, index + 1

    tags: list[str] = []
    index += 1
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped:
            index += 1
            continue
        if not raw_line[:1].isspace():
            break
        if not stripped.startswith("- "):
            return None, index
        scalar = _simple_yaml_scalar(stripped[1:])
        if scalar is None:
            return None, index
        tags.append(scalar)
        index += 1
    return tags, index


def _simple_yaml_list(raw: str) -> list[str] | None:
    if not raw.strip():
        return []
    values: list[str] = []
    for part in raw.split(","):
        value = _simple_yaml_scalar(part)
        if value is None:
            return None
        values.append(value)
    return values


def _simple_yaml_scalar(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return ""
    value = _strip_simple_comment(value)
    if not value:
        return ""
    if value[0] in "[{|>}*&!":
        return None
    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'":
            return None
        return value[1:-1].replace("''", "'")
    if value[0] == '"':
        if len(value) < 2 or value[-1] != '"' or "\\" in value:
            return None
        return value[1:-1]
    return value


def _strip_simple_comment(value: str) -> str:
    marker = value.find(" #")
    if marker == -1:
        return value
    return value[:marker].rstrip()


def _frontmatter_tags(frontmatter: dict[str, Any]) -> list[str]:
    raw = frontmatter.get(_USER_TAGS_KEY)
    if isinstance(raw, str):
        parts = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple)):
        parts = [str(part) for part in raw]
    else:
        return []
    return [part for part in parts if part and part.strip()]


def _dedup_tags(tokens: Iterable[str]) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        tag = token.strip().lstrip(_TAG_SIGILS).strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tuple(tags)


def _relative_path(path: Path, archive_root: Path) -> str:
    try:
        return path.relative_to(archive_root).as_posix()
    except ValueError:
        return str(path)


def _str_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section(
    sections: tuple[PlanHeaderSection, ...],
    kind: PlanHeaderSectionKind,
) -> PlanHeaderSection | None:
    return next((section for section in sections if section.kind is kind), None)
