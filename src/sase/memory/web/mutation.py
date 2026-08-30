"""CLI-free create/delete engine for memory-web strands.

This is the only code that writes memory-web strand files. It has no Textual
import. Validation is pure; disk writes are atomic and digest-guarded, the
same shape as :mod:`sase.memory.mutation`'s flat-note engine. Every create or
delete also regenerates and atomically overwrites the owning web descriptor's
managed roster region, so the descriptor never drifts out of sync with its
strand directory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.content_layout import LayoutCollisionError
from sase.core.glossary_facade import GlossaryInputEntry, validate_glossary_entries
from sase.memory.atomic_write import (
    AtomicWriteConflictError,
    backup_path_for,
    content_digest,
    write_bytes_atomically,
)
from sase.memory.mutation_models import MemoryConflictError, MemoryScopeKind
from sase.memory.paths import memory_write_root
from sase.memory.web.discovery import discover_memory_webs
from sase.memory.web.frontmatter import parse_memory_strand, render_strand_frontmatter
from sase.memory.web.models import MemoryStrand, MemoryWeb, MemoryWebDiscovery
from sase.memory.web.mutation_models import (
    MemoryStrandDraft,
    MemoryStrandDraftValidation,
    MemoryStrandMutationError,
    MemoryStrandMutationOutcome,
    MemoryStrandValidationError,
)
from sase.memory.web.mutation_validate import validate_memory_strand_draft
from sase.memory.web.roster import render_web_descriptor_with_roster


def memory_strand_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of a memory strand's on-disk bytes."""
    return content_digest(data)


def create_memory_strand(
    *,
    scope_key: str,
    content_root: Path | str,
    web_slug: str,
    slug: str,
    keyword: str | None = None,
    aliases: Sequence[str] = (),
    summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    body: str = "",
    scope_kind: MemoryScopeKind = "project",
) -> MemoryStrandMutationOutcome:
    """Create a new strand under an existing web's strand directory.

    Validates that ``slug``/``keyword``/``aliases`` do not collide with any
    strand already in the web (a successful
    :func:`sase.memory.web.lookup.resolve_memory_strand` against the existing
    web means a collision), writes the new strand file atomically to the
    canonical write root, then regenerates and atomically overwrites the
    owning web descriptor's managed roster region.
    """
    root = _resolve_content_root(content_root)
    web = _require_existing_web(root, web_slug)
    validation = validate_memory_strand_draft(
        web=web,
        slug=slug,
        keyword=keyword,
        aliases=aliases,
        summary=summary,
        metadata=metadata,
    )
    draft = _require_valid_draft(validation)

    dest = memory_write_root(root) / web.slug / f"{draft.slug}.md"
    if dest.exists():
        raise MemoryStrandMutationError(
            f"refusing to overwrite existing memory strand: {dest}"
        )

    content = render_strand_frontmatter(
        keyword=draft.keyword,
        aliases=draft.aliases,
        summary=draft.summary,
        metadata=draft.metadata,
        body=body,
    )
    new_strand, parse_error = parse_memory_strand(
        root=web.root,
        memory_root=web.memory_root,
        web_slug=web.slug,
        path=dest,
        text=content,
        link_reference=web.link_reference,
        link_rendering=web.link_rendering,
    )
    if parse_error is not None or new_strand is None:
        raise MemoryStrandMutationError(
            parse_error or f"failed to parse the rendered memory strand: {dest}"
        )

    updated_web = replace(
        web,
        strands=tuple(
            sorted((*web.strands, new_strand), key=lambda strand: strand.slug)
        ),
    )
    _require_valid_glossary(updated_web)
    descriptor_content, roster_error = render_web_descriptor_with_roster(updated_web)
    if roster_error is not None or descriptor_content is None:
        raise MemoryStrandMutationError(
            roster_error or f"failed to render memory web roster: {web.path}"
        )

    try:
        write_bytes_atomically(dest, content.encode("utf-8"), overwrite=False)
    except AtomicWriteConflictError as exc:
        raise MemoryStrandMutationError(
            f"refusing to overwrite existing memory strand: {dest}"
        ) from exc
    write_bytes_atomically(web.path, descriptor_content.encode("utf-8"), overwrite=True)

    return MemoryStrandMutationOutcome(
        scope_key=scope_key,
        content_root=root,
        web_slug=web.slug,
        relative_path=new_strand.relative_path,
        slug=new_strand.slug,
        keyword=new_strand.keyword,
        aliases=new_strand.aliases,
        summary=new_strand.summary,
        metadata=new_strand.metadata,
    )


def delete_memory_strand(
    *,
    scope_key: str,
    content_root: Path | str,
    web_slug: str,
    slug: str,
    expected_digest: str,
    scope_kind: MemoryScopeKind = "project",
) -> MemoryStrandMutationOutcome:
    """Backup and unlink a memory-web strand after a digest check.

    Raises :class:`sase.memory.mutation_models.MemoryConflictError` when
    ``expected_digest`` no longer matches the on-disk strand, exactly like
    :func:`sase.memory.mutation.delete_memory_note` does for flat notes. On
    success, also regenerates and atomically overwrites the owning web
    descriptor's managed roster region.
    """
    root = _resolve_content_root(content_root)
    web = _require_existing_web(root, web_slug)
    strand = _require_existing_strand(web, slug)

    source = strand.path
    original = _read_strand_bytes(source)
    _require_digest(source, original, expected_digest)

    remaining = tuple(
        candidate for candidate in web.strands if candidate.slug != strand.slug
    )
    updated_web = replace(web, strands=remaining)
    _require_valid_glossary(updated_web)
    descriptor_content, roster_error = render_web_descriptor_with_roster(updated_web)
    if roster_error is not None or descriptor_content is None:
        raise MemoryStrandMutationError(
            roster_error or f"failed to render memory web roster: {web.path}"
        )

    backup_path = backup_path_for(
        content_root=root,
        scope_key=scope_key,
        scope_kind=scope_kind,
        label=f"{web.slug}-{strand.slug}",
    )
    try:
        write_bytes_atomically(backup_path, original, overwrite=False)
    except AtomicWriteConflictError as exc:
        raise MemoryStrandMutationError(
            f"refusing to overwrite existing memory strand backup: {backup_path}"
        ) from exc
    current = _read_strand_bytes(source)
    if current != original:
        raise MemoryConflictError(source)
    source.unlink()
    write_bytes_atomically(web.path, descriptor_content.encode("utf-8"), overwrite=True)

    return MemoryStrandMutationOutcome(
        scope_key=scope_key,
        content_root=root,
        web_slug=web.slug,
        relative_path=strand.relative_path,
        slug=strand.slug,
        keyword=strand.keyword,
        aliases=strand.aliases,
        summary=strand.summary,
        metadata=strand.metadata,
        backup_path=backup_path,
    )


def _require_valid_draft(
    validation: MemoryStrandDraftValidation,
) -> MemoryStrandDraft:
    if validation.by_field or validation.draft is None:
        raise MemoryStrandValidationError(validation)
    return validation.draft


def _resolve_content_root(content_root: Path | str) -> Path:
    return Path(content_root).expanduser().resolve(strict=False)


def _discover_webs(root: Path) -> MemoryWebDiscovery:
    try:
        return discover_memory_webs(root)
    except LayoutCollisionError as exc:
        raise MemoryStrandMutationError(str(exc)) from exc
    except OSError as exc:
        raise MemoryStrandMutationError(
            f"failed to read memory webs under {root}: {exc}"
        ) from exc


def _require_existing_web(root: Path, web_slug: str) -> MemoryWeb:
    discovery = _discover_webs(root)
    for web in discovery.webs:
        if web.slug == web_slug:
            return web
    raise MemoryStrandMutationError(f"memory web does not exist: {web_slug}")


def _require_valid_glossary(web: MemoryWeb) -> None:
    """Raise a clear error when *web*'s strands would fail glossary validation.

    ``render_web_descriptor_with_roster`` calls the same underlying Rust
    catalog builder for ``roster: inline`` webs and raises a raw
    :class:`ValueError` (e.g. "needs a definition") when a strand's body is
    empty. Checking this up front, with the same rule
    :func:`sase.memory.web.validation.validate_memory_webs` applies to every
    web regardless of roster style, surfaces one clear, typed error instead.
    """
    if not web.strands:
        return
    entries = [
        GlossaryInputEntry(
            term=strand.keyword, definition=strand.body, aliases=strand.aliases
        )
        for strand in web.strands
    ]
    diagnostics = validate_glossary_entries(entries)
    blockers = [
        diagnostic.message
        for diagnostic in diagnostics
        if diagnostic.severity.lower() in {"error", "fatal"}
    ]
    if blockers:
        raise MemoryStrandMutationError(
            f"memory web {web.slug} strand roster would become invalid: "
            + "; ".join(blockers)
        )


def _require_existing_strand(web: MemoryWeb, slug: str) -> MemoryStrand:
    for strand in web.strands:
        if strand.slug == slug:
            return strand
    raise MemoryStrandMutationError(f"memory strand does not exist: {web.slug}:{slug}")


def _read_strand_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MemoryStrandMutationError(
            f"failed to read memory strand: {path}"
        ) from exc


def _require_digest(path: Path, data: bytes, expected_digest: str) -> None:
    if memory_strand_digest(data) != expected_digest:
        raise MemoryConflictError(path)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryStrandMutationError(
            f"memory strand is not valid UTF-8: {path}"
        ) from exc


__all__ = [
    "MemoryConflictError",
    "MemoryStrandDraft",
    "MemoryStrandDraftValidation",
    "MemoryStrandMutationError",
    "MemoryStrandMutationOutcome",
    "MemoryStrandValidationError",
    "create_memory_strand",
    "delete_memory_strand",
    "memory_strand_digest",
    "validate_memory_strand_draft",
]
