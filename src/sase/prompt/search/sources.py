"""Load and unify prompt hits from the SDD snapshot and local-history stores.

This is the read layer: it discovers exported and historical
``sdd/plans/*/prompts/**`` snapshots (across the nested, legacy-root, and local
``.sase/sdd`` layouts), adapts the
machine-wide prompt history into the same :class:`PromptHit` shape, and collapses
cross-store duplicates by content digest. It is read-only — neither store is
written and no lock is taken.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.history.prompt import list_prompt_records
from sase.history.prompt_metadata import clean_prompt_preview, summarize_prompt_for_list
from sase.prompt.search.dates import resolve_sdd_date
from sase.prompt.search.model import PromptHit, PromptSource
from sase.sdd._paths import sdd_prompt_roots
from sase.sdd.artifact_links import (
    SddArtifactLink,
    SddArtifactLinkKind,
    SddArtifactLinkType,
    parse_sdd_artifact_link,
)
from sase.sdd.frontmatter import parse_frontmatter

# Frontmatter key for free-form user tags, mirroring ``prompt export`` so a
# round-tripped snapshot's tags are recovered here.
_USER_TAGS_KEY = "prompt_tags"
# Marker sigils stripped when normalizing an xprompt chip into a plain tag token.
_TAG_SIGILS = "#@"


def collect_prompt_hits(
    sources: Iterable[PromptSource],
    base_dir: Path,
) -> list[PromptHit]:
    """Return the unified, de-duplicated corpus for the selected *sources*.

    SDD hits are listed before local hits. When both sources are selected, a
    local entry whose ``text_sha256`` equals an SDD snapshot's is collapsed into
    that snapshot (which is annotated :attr:`PromptHit.also_in_local`); the
    de-dup is strictly digest-based and never collapses a hit it cannot prove is
    a duplicate. Ranking is the engine's job; the order here is only stable.
    """
    selected = set(sources)
    sdd_hits = load_sdd_prompt_hits(base_dir) if PromptSource.SDD in selected else []
    local_hits = load_local_prompt_hits() if PromptSource.LOCAL in selected else []
    return _dedup_hits(sdd_hits, local_hits)


def load_sdd_prompt_hits(base_dir: Path) -> list[PromptHit]:
    """Discover and parse every SDD prompt snapshot under *base_dir*.

    Discovery covers nested ``sdd/plans/*/prompts/`` directories, the legacy root
    ``prompts/``, and the project-local ``.sase/sdd`` layout (see
    :func:`_sdd_prompt_roots`), so a normal project-root search surfaces local
    SDD snapshots alongside committed ones. Files are de-duplicated by resolved
    path so overlapping roots are scanned once. A file that cannot be read is
    skipped rather than failing the whole scan.
    """
    hits: list[PromptHit] = []
    seen: set[Path] = set()
    for root in _sdd_prompt_roots(base_dir):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            hit = _load_sdd_file(path, base_dir)
            if hit is not None:
                hits.append(hit)
    return hits


def _sdd_prompt_roots(base_dir: Path) -> list[Path]:
    """Return the de-duplicated prompt-discovery roots for *base_dir*.

    Combines :func:`sdd_prompt_roots` (canonical nested prompt directories and
    legacy ``prompts``/``specs`` aliases) with the project-local ``.sase/sdd``
    store. A normal project-root search therefore includes its nested prompts
    instead of only finding them when *base_dir* is already that SDD root. Roots are
    returned once each; :func:`load_sdd_prompt_hits` still de-dups by resolved
    path so any overlap is scanned a single time.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    local_sdd = base_dir / ".sase" / "sdd"
    for root in (
        *sdd_prompt_roots(base_dir),
        *sdd_prompt_roots(local_sdd),
    ):
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def _load_sdd_file(path: Path, base_dir: Path) -> PromptHit | None:
    """Parse one SDD snapshot into a :class:`PromptHit`, tolerating bad files."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # ``parse_frontmatter`` is itself malformed-tolerant: invalid YAML yields an
    # empty frontmatter and the raw content as body, so a single broken file
    # never aborts the scan.
    artifact_link = parse_sdd_artifact_link(content)
    frontmatter, _, _ = parse_frontmatter(content)
    text = artifact_link.body.strip()
    locator = path.stem
    recorded_sha = _str_or_none(frontmatter.get("sha256"))

    return PromptHit(
        source=PromptSource.SDD,
        id=locator,
        text=text,
        title=_derive_title(text, locator),
        date=resolve_sdd_date(frontmatter, path),
        text_sha256=recorded_sha or _sha256(text),
        path=_relative_path(path, base_dir),
        plan=_artifact_plan_reference(artifact_link, path, base_dir),
        tags=_sdd_tags(frontmatter, text),
        cancelled=None,
        also_in_local=False,
    )


def load_local_prompt_hits() -> list[PromptHit]:
    """Adapt the machine-wide prompt history into :class:`PromptHit` records.

    Both launched and cancelled prompts are loaded; narrowing to cancelled-only
    is the engine's ``cancelled_only`` filter, not this loader's job.
    """
    return [
        _local_hit(record) for record in list_prompt_records(include_cancelled=True)
    ]


def _local_hit(record: Any) -> PromptHit:
    """Build a local :class:`PromptHit` from a prompt-history record."""
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
        tags=_body_tags(text),
        cancelled=record.cancelled,
        also_in_local=False,
    )


def _dedup_hits(
    sdd_hits: list[PromptHit],
    local_hits: list[PromptHit],
) -> list[PromptHit]:
    """Collapse same-digest local entries into their SDD snapshot."""
    sdd_shas = {hit.text_sha256 for hit in sdd_hits if hit.text_sha256}
    local_shas = {hit.text_sha256 for hit in local_hits if hit.text_sha256}

    result: list[PromptHit] = []
    for hit in sdd_hits:
        if hit.text_sha256 and hit.text_sha256 in local_shas:
            result.append(replace(hit, also_in_local=True))
        else:
            result.append(hit)
    for hit in local_hits:
        if hit.text_sha256 and hit.text_sha256 in sdd_shas:
            continue  # the same prompt is already shown as its SDD snapshot
        result.append(hit)
    return result


# ---------------------------------------------------------------------------
# Field derivation helpers
# ---------------------------------------------------------------------------


def _derive_title(text: str, fallback: str) -> str:
    """Return a cleaned one-line preview of *text*, falling back to *fallback*."""
    try:
        title = clean_prompt_preview(text)
    except Exception:
        title = " ".join(text.split())
    return title or fallback


def _sdd_tags(frontmatter: dict[str, Any], text: str) -> tuple[str, ...]:
    """Return ``prompt_tags`` frontmatter plus embedded body chips as tags."""
    return _dedup_tags([*_frontmatter_tags(frontmatter), *_body_tags(text)])


def _body_tags(text: str) -> tuple[str, ...]:
    """Return sigil-stripped ``#xprompt`` chip names embedded in *text*.

    Only embedded xprompt chips count as tags. The fixed set of runner-control
    ``%directive`` tokens (``%model``, ``%id``, ``%wait`` …) are execution
    mechanics rather than content tags, so they are deliberately excluded to
    keep the tag space high-signal.
    """
    try:
        summary = summarize_prompt_for_list(text)
    except Exception:
        return ()
    return _dedup_tags(summary.xprompts)


def _frontmatter_tags(frontmatter: dict[str, Any]) -> list[str]:
    """Return ``prompt_tags`` values, accepting a list or a delimited string."""
    raw = frontmatter.get(_USER_TAGS_KEY)
    if isinstance(raw, str):
        parts = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple)):
        parts = [str(part) for part in raw]
    else:
        return []
    return [part for part in parts if part and part.strip()]


def _dedup_tags(tokens: Iterable[str]) -> tuple[str, ...]:
    """Normalize tokens to plain tags, de-duplicated, order preserved."""
    tags: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        tag = token.strip().lstrip(_TAG_SIGILS).strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tuple(tags)


def _relative_path(path: Path, base_dir: Path) -> str:
    """Return *path* relative to *base_dir*, or its string form if unrelated."""
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _artifact_plan_reference(
    link: SddArtifactLink, source: Path, base_dir: Path
) -> str | None:
    """Project a plan label only when mixed representations agree."""
    if link.link_type is not SddArtifactLinkType.PLAN:
        return None
    if link.kind is not SddArtifactLinkKind.MIXED:
        return link.reference
    if link.target is None or link.label is None or link.legacy is None:
        return None
    canonical = (source.parent / link.target).resolve()
    if link.legacy.format == "markdown":
        legacy = (source.parent / link.legacy.target).resolve()
    else:
        target = Path(link.legacy.target)
        candidates = [
            base_dir / target,
            base_dir / "sdd" / target,
            base_dir / ".sase" / "sdd" / target,
            *(ancestor / target for ancestor in source.parents),
        ]
        legacy = next(
            (candidate.resolve() for candidate in candidates if candidate.exists()),
            candidates[0].resolve(),
        )
    return link.label if canonical == legacy else None


def _str_or_none(value: Any) -> str | None:
    """Return a stripped non-empty string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _sha256(text: str) -> str:
    """Return the lowercase SHA-256 hex digest of *text* (parity with history)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
