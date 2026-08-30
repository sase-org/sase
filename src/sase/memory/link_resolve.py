"""Resolve authored memory-link targets against a scoped memory universe."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Literal

from sase.memory.notes import MemoryNote
from sase.memory.paths import memory_note_relative_path
from sase.memory.web.lookup import (
    MemoryWebLookupError,
    normalize_memory_web_reference,
    resolve_memory_strand,
)
from sase.memory.web.models import MemoryStrand, MemoryWeb, ScopedMemoryWeb, WebScope

_MAX_CANDIDATES = 5


@dataclass(frozen=True, slots=True)
class MemoryNoteLinkTarget:
    """A link target resolved to one flat memory note."""

    raw: str
    note: MemoryNote
    address: str
    kind: Literal["note"] = "note"


@dataclass(frozen=True, slots=True)
class MemoryStrandLinkTarget:
    """A link target resolved to one memory-web strand."""

    raw: str
    web: MemoryWeb
    strand: MemoryStrand
    scope: WebScope
    address: str
    kind: Literal["strand"] = "strand"


@dataclass(frozen=True, slots=True)
class MemoryWebDescriptorLinkTarget:
    """A link target resolved to one memory-web descriptor note."""

    raw: str
    web: MemoryWeb
    address: str
    relative_path: str
    kind: Literal["descriptor"] = "descriptor"


@dataclass(frozen=True, slots=True)
class UnresolvedMemoryLinkTarget:
    """A link target that did not resolve, with optional near-miss candidates."""

    raw: str
    candidates: tuple[str, ...] = ()
    kind: Literal["unresolved"] = "unresolved"


type MemoryLinkTarget = (
    MemoryNoteLinkTarget
    | MemoryStrandLinkTarget
    | MemoryWebDescriptorLinkTarget
    | UnresolvedMemoryLinkTarget
)


def resolve_memory_link_target(
    raw_target: str,
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_note: MemoryNote | None = None,
    source_strand: MemoryStrand | None = None,
) -> MemoryLinkTarget | None:
    """Resolve one raw ``[[target]]`` body target.

    ``None`` means the target resolved to the source note or strand and was dropped as
    a self-link. Unresolved and ambiguous targets return data, not exceptions, so read
    paths can render or warn without failing.
    """

    target = raw_target.strip()
    if not target:
        return UnresolvedMemoryLinkTarget(raw=raw_target)

    by_web_slug = {scoped.slug: scoped for scoped in scoped_webs}

    colon_target = _resolve_colon_target(
        target,
        by_web_slug=by_web_slug,
        notes=notes,
        scoped_webs=scoped_webs,
        source_strand=source_strand,
    )
    if not isinstance(colon_target, _NotATargetForm):
        return colon_target

    slash_target = _resolve_slash_target(
        target,
        by_web_slug=by_web_slug,
        notes=notes,
        scoped_webs=scoped_webs,
        source_strand=source_strand,
    )
    if not isinstance(slash_target, _NotATargetForm):
        return slash_target

    note_target = _resolve_note_target(
        target,
        notes=notes,
        scoped_webs=scoped_webs,
        source_note=source_note,
    )
    if not isinstance(note_target, _NotATargetForm):
        return note_target

    bare_target = _resolve_bare_target(
        target,
        notes=notes,
        scoped_webs=scoped_webs,
        by_web_slug=by_web_slug,
        source_note=source_note,
        source_strand=source_strand,
    )
    if not isinstance(bare_target, _NotATargetForm):
        return bare_target

    return UnresolvedMemoryLinkTarget(
        raw=target,
        candidates=_candidate_addresses(target, notes=notes, scoped_webs=scoped_webs),
    )


@dataclass(frozen=True, slots=True)
class _NotATargetForm:
    pass


_NOT_A_TARGET_FORM = _NotATargetForm()
type _ResolvedOrNot = MemoryLinkTarget | None | _NotATargetForm


def _resolve_colon_target(
    target: str,
    *,
    by_web_slug: dict[str, ScopedMemoryWeb],
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_strand: MemoryStrand | None,
) -> _ResolvedOrNot:
    if ":" not in target:
        return _NOT_A_TARGET_FORM

    web_slug, _, keyword = target.partition(":")
    web_slug = web_slug.strip()
    keyword = keyword.strip()
    if not web_slug or not keyword:
        return UnresolvedMemoryLinkTarget(
            raw=target,
            candidates=_candidate_addresses(
                target, notes=notes, scoped_webs=scoped_webs
            ),
        )

    scoped = by_web_slug.get(web_slug)
    if scoped is None:
        return UnresolvedMemoryLinkTarget(
            raw=target,
            candidates=_candidate_addresses(
                web_slug, notes=notes, scoped_webs=scoped_webs
            ),
        )
    return _resolve_strand_reference(
        target,
        scoped=scoped,
        reference=keyword,
        notes=notes,
        scoped_webs=scoped_webs,
        source_strand=source_strand,
    )


def _resolve_slash_target(
    target: str,
    *,
    by_web_slug: dict[str, ScopedMemoryWeb],
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_strand: MemoryStrand | None,
) -> _ResolvedOrNot:
    parts = _target_path_parts(target)
    if len(parts) != 2:
        return _NOT_A_TARGET_FORM

    web_slug, slug = parts
    scoped = by_web_slug.get(web_slug)
    if scoped is None:
        return _NOT_A_TARGET_FORM

    if slug.endswith(".md"):
        slug = slug[: -len(".md")]
    strand = next((item for item in scoped.strands if item.slug == slug), None)
    if strand is None:
        return UnresolvedMemoryLinkTarget(
            raw=target,
            candidates=_candidate_addresses(
                target, notes=notes, scoped_webs=scoped_webs
            ),
        )
    return _strand_target(
        target,
        scoped=scoped,
        strand=strand,
        source_strand=source_strand,
    )


def _resolve_note_target(
    target: str,
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_note: MemoryNote | None,
) -> _ResolvedOrNot:
    if not target.endswith(".md"):
        return _NOT_A_TARGET_FORM

    note = _note_by_path(notes).get(_note_lookup_key(target))
    if note is None:
        return UnresolvedMemoryLinkTarget(
            raw=target,
            candidates=_candidate_addresses(
                target, notes=notes, scoped_webs=scoped_webs
            ),
        )
    return _note_or_descriptor_target(
        target,
        note=note,
        scoped_webs=scoped_webs,
        source_note=source_note,
    )


def _resolve_bare_target(
    target: str,
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    by_web_slug: dict[str, ScopedMemoryWeb],
    source_note: MemoryNote | None,
    source_strand: MemoryStrand | None,
) -> _ResolvedOrNot:
    if source_strand is not None:
        scoped = by_web_slug.get(source_strand.web_slug)
        if scoped is not None:
            try:
                return _resolve_strand_reference(
                    target,
                    scoped=scoped,
                    reference=target,
                    notes=notes,
                    scoped_webs=scoped_webs,
                    source_strand=source_strand,
                )
            except _UnknownBareStrand:
                pass

    note = _note_by_stem(notes).get(target)
    if note is not None:
        return _note_or_descriptor_target(
            target,
            note=note,
            scoped_webs=scoped_webs,
            source_note=source_note,
        )

    scoped = by_web_slug.get(target)
    if scoped is not None:
        return _descriptor_target(target, scoped=scoped, source_note=source_note)

    return _NOT_A_TARGET_FORM


class _UnknownBareStrand(Exception):
    """Internal signal allowing bare-token lookup to fall through."""


def _resolve_strand_reference(
    raw: str,
    *,
    scoped: ScopedMemoryWeb,
    reference: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_strand: MemoryStrand | None,
) -> MemoryStrandLinkTarget | UnresolvedMemoryLinkTarget | None:
    merged_web = replace(scoped.web, strands=scoped.strands)
    try:
        strand = resolve_memory_strand(merged_web, reference)
    except MemoryWebLookupError as exc:
        if raw == reference and str(exc).startswith("unknown memory strand"):
            raise _UnknownBareStrand from exc
        return UnresolvedMemoryLinkTarget(
            raw=raw,
            candidates=_candidate_addresses(raw, notes=notes, scoped_webs=scoped_webs),
        )
    return _strand_target(
        raw,
        scoped=scoped,
        strand=strand,
        source_strand=source_strand,
    )


def _strand_target(
    raw: str,
    *,
    scoped: ScopedMemoryWeb,
    strand: MemoryStrand,
    source_strand: MemoryStrand | None,
) -> MemoryStrandLinkTarget | None:
    if source_strand is not None and (
        source_strand.web_slug,
        source_strand.slug,
    ) == (strand.web_slug, strand.slug):
        return None

    origin = scoped.origins.get(strand.slug)
    scope: WebScope = origin.scope if origin is not None else "project"
    return MemoryStrandLinkTarget(
        raw=raw,
        web=replace(scoped.web, strands=scoped.strands),
        strand=strand,
        scope=scope,
        address=f"{scoped.slug}:{strand.slug}",
    )


def _note_or_descriptor_target(
    raw: str,
    *,
    note: MemoryNote,
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_note: MemoryNote | None,
) -> MemoryNoteLinkTarget | MemoryWebDescriptorLinkTarget | None:
    if _same_note(note, source_note):
        return None
    descriptor = _descriptor_for_note(note, scoped_webs)
    if descriptor is not None:
        return _descriptor_target(raw, scoped=descriptor, source_note=source_note)
    return MemoryNoteLinkTarget(raw=raw, note=note, address=_note_address(note))


def _descriptor_target(
    raw: str,
    *,
    scoped: ScopedMemoryWeb,
    source_note: MemoryNote | None,
) -> MemoryWebDescriptorLinkTarget | None:
    if (
        source_note is not None
        and source_note.relative_path == scoped.web.relative_path
    ):
        return None
    web = replace(scoped.web, strands=scoped.strands)
    return MemoryWebDescriptorLinkTarget(
        raw=raw,
        web=web,
        address=scoped.slug,
        relative_path=scoped.web.relative_path,
    )


def _same_note(note: MemoryNote, other: MemoryNote | None) -> bool:
    return other is not None and note.relative_path == other.relative_path


def _descriptor_for_note(
    note: MemoryNote, scoped_webs: tuple[ScopedMemoryWeb, ...]
) -> ScopedMemoryWeb | None:
    if not note.is_web_descriptor:
        return None
    for scoped in scoped_webs:
        if scoped.web.relative_path == note.relative_path:
            return scoped
    return None


def _note_by_path(notes: tuple[MemoryNote, ...]) -> dict[str, MemoryNote]:
    by_path: dict[str, MemoryNote] = {}
    for note in notes:
        by_path.setdefault(_note_lookup_key(note.relative_path), note)
        by_path.setdefault(_note_address(note), note)
    return by_path


def _note_by_stem(notes: tuple[MemoryNote, ...]) -> dict[str, MemoryNote]:
    by_stem: dict[str, MemoryNote] = {}
    for note in notes:
        by_stem.setdefault(PurePosixPath(_note_address(note)).stem, note)
    return by_stem


def _note_lookup_key(target: str) -> str:
    path = PurePosixPath(target.strip().replace("\\", "/"))
    relative = memory_note_relative_path(path.as_posix())
    if relative is not None:
        return relative.as_posix()
    return path.as_posix()


def _note_address(note: MemoryNote) -> str:
    relative = memory_note_relative_path(note.relative_path)
    if relative is None:
        return PurePosixPath(note.relative_path).as_posix()
    return relative.as_posix()


def _target_path_parts(target: str) -> tuple[str, ...]:
    path = PurePosixPath(target.strip().replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return ()
    return tuple(path.parts)


def _candidate_addresses(
    target: str,
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[str, ...]:
    needle = _candidate_key(target)
    if not needle:
        return ()

    candidates: list[str] = []
    for address, keys in _candidate_entries(notes=notes, scoped_webs=scoped_webs):
        if address in candidates:
            continue
        if any(_candidate_matches(needle, key) for key in keys):
            candidates.append(address)
        if len(candidates) == _MAX_CANDIDATES:
            break
    return tuple(candidates)


def _candidate_entries(
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    entries: list[tuple[str, tuple[str, ...]]] = []
    for note in notes:
        address = _note_address(note)
        entries.append((address, (address, PurePosixPath(address).stem)))
    for scoped in scoped_webs:
        entries.append((scoped.slug, (scoped.slug, scoped.web.description or "")))
        for strand in scoped.strands:
            address = f"{scoped.slug}:{strand.slug}"
            entries.append(
                (
                    address,
                    (
                        address,
                        f"{scoped.slug}/{strand.slug}",
                        strand.slug,
                        strand.keyword,
                        *strand.aliases,
                    ),
                )
            )
    return tuple(entries)


def _candidate_matches(needle: str, value: str) -> bool:
    key = _candidate_key(value)
    return bool(key) and (key.startswith(needle) or needle in key)


def _candidate_key(value: str) -> str:
    normalized = value.strip().removesuffix(".md")
    normalized = normalized.replace("/", " ").replace(":", " ")
    return normalize_memory_web_reference(normalized)


__all__ = [
    "MemoryLinkTarget",
    "MemoryNoteLinkTarget",
    "MemoryStrandLinkTarget",
    "MemoryWebDescriptorLinkTarget",
    "UnresolvedMemoryLinkTarget",
    "resolve_memory_link_target",
]
