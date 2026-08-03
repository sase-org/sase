"""Load and unify prompt hits from the canonical archive and local history.

This read-only layer inventories ``prompts/<YYYYMM>/*.md`` in the agents
sidecar, adapts machine-wide prompt history into the same :class:`PromptHit`
shape, and collapses cross-store duplicates by content digest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agents_sync.prompt_archive.validation import list_prompt_archive_files
from sase.history.prompt import list_prompt_records
from sase.history.prompt_metadata import clean_prompt_preview, summarize_prompt_for_list
from sase.prompt.search.dates import resolve_archive_date
from sase.prompt.search.model import PromptHit, PromptSource
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_header_block import parse_plan_header_block

_USER_TAGS_KEY = "prompt_tags"
_TAG_SIGILS = "#@"


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
    for archived in list_prompt_archive_files(root):
        hit = _load_archive_file(
            archived.path,
            root,
            plan=archived.plan_label,
            artifact_count=archived.artifact_count,
        )
        if hit is not None:
            hits.append(hit)
    return hits


def _load_archive_file(
    path: Path,
    archive_root: Path,
    *,
    plan: str | None,
    artifact_count: int,
) -> PromptHit | None:
    """Parse one canonical archive file, tolerating an unreadable entry."""

    try:
        content = path.read_text(encoding="utf-8")
        text = parse_plan_header_block(content).body.strip()
    except (OSError, UnicodeError, RuntimeError, ValueError):
        return None

    frontmatter, _, _ = parse_frontmatter(content)
    locator = path.stem
    recorded_sha = _str_or_none(frontmatter.get("sha256"))
    return PromptHit(
        source=PromptSource.ARCHIVE,
        id=locator,
        text=text,
        title=_derive_title(text, locator),
        date=resolve_archive_date(frontmatter, path),
        text_sha256=recorded_sha or _sha256(text),
        path=_relative_path(path, archive_root),
        plan=plan,
        artifact_count=artifact_count,
        tags=_archive_tags(frontmatter, text),
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
    return PromptHit(
        source=PromptSource.LOCAL,
        id=record.id,
        text=text,
        title=_derive_title(text, record.id),
        date=record.last_used,
        text_sha256=record.text_sha256,
        path=None,
        plan=None,
        artifact_count=None,
        tags=_body_tags(text),
        cancelled=record.cancelled,
        also_in_local=False,
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


def _derive_title(text: str, fallback: str) -> str:
    try:
        title = clean_prompt_preview(text)
    except Exception:
        title = " ".join(text.split())
    return title or fallback


def _archive_tags(frontmatter: dict[str, Any], text: str) -> tuple[str, ...]:
    return _dedup_tags([*_frontmatter_tags(frontmatter), *_body_tags(text)])


def _body_tags(text: str) -> tuple[str, ...]:
    try:
        summary = summarize_prompt_for_list(text)
    except Exception:
        return ()
    return _dedup_tags(summary.xprompts)


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
