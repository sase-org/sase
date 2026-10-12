"""Warm-corpus name candidates for the Node Finder Archive section."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...models.agent_archive_view import agents_archive_view_enabled


@dataclass(frozen=True, slots=True)
class ArchiveNameCandidate:
    name: str
    status: str = ""
    model: str = ""
    outcome: str = ""
    row: Mapping[str, Any] = field(default_factory=dict)


def archive_name_loader_for_owner(
    owner: Any,
) -> Callable[[], tuple[ArchiveNameCandidate, ...]] | None:
    """Capture the held corpus only; never compile or warm it here."""
    if not agents_archive_view_enabled():
        return None
    controller = getattr(owner, "_agents_archive_controller", None)
    corpus = getattr(controller, "corpus", None)
    profile = getattr(controller, "profile", None)
    if corpus is None or getattr(controller, "status", None) != "warm":
        return None
    return lambda: load_archive_name_candidates(corpus, profile)


def load_archive_name_candidates(
    corpus: Any,
    profile: Any = None,
) -> tuple[ArchiveNameCandidate, ...]:
    """Read light names from every day group of an already-warm corpus."""
    summary = corpus.summary("", group_by="day", profile=profile)
    candidates: list[ArchiveNameCandidate] = []
    seen: set[str] = set()
    for group in summary.get("groups", ()):
        if not isinstance(group, Mapping):
            continue
        key = group.get("key")
        if not isinstance(key, str):
            continue
        try:
            limit = max(0, int(group.get("count", 0) or 0))
            payload = corpus.rows(
                "",
                group_by="day",
                group_key=key,
                offset=0,
                limit=limit,
                profile=profile,
            )
        except Exception:
            continue
        rows = [row for row in payload.get("rows", ()) if isinstance(row, Mapping)]
        member_rows: list[Mapping[str, Any]] = []
        for row in rows:
            if row.get("container") is not True:
                member_rows.append(row)
                continue
            container_key = row.get("container_key")
            if not isinstance(container_key, str) or not container_key:
                continue
            try:
                expanded = corpus.rows(
                    "",
                    group_by="day",
                    group_key=key,
                    offset=0,
                    limit=max(1, int(row.get("member_count", 0) or 0) + 1),
                    expanded_container_keys=(container_key,),
                    profile=profile,
                )
            except Exception:
                continue
            member_rows.extend(
                candidate
                for candidate in expanded.get("rows", ())
                if isinstance(candidate, Mapping)
                and candidate.get("container") is not True
            )
        for row in member_rows:
            if not isinstance(row, Mapping):
                continue
            name = _row_name(row)
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            candidates.append(
                ArchiveNameCandidate(
                    name=name,
                    status=str(row.get("status") or ""),
                    model=str(row.get("model") or ""),
                    outcome=str(row.get("outcome") or ""),
                    row=dict(row),
                )
            )
    return tuple(candidates)


def search_archive_name_candidates(
    candidates: tuple[ArchiveNameCandidate, ...],
    query: str,
    *,
    limit: int = 5,
) -> tuple[ArchiveNameCandidate, ...]:
    """Return the five best name matches using Node Finder's fuzzy scorer."""
    tokens = tuple(token for token in query.split() if token)
    if not tokens:
        return candidates[:limit]

    from sase.core.fuzzy_facade import fuzzy_tier_score

    ranked: list[tuple[tuple[int, int, int], ArchiveNameCandidate]] = []
    for pos, candidate in enumerate(candidates):
        tiers: list[int] = []
        total = 0
        for token in tokens:
            match = fuzzy_tier_score(token, candidate.name)
            if match is None:
                break
            tier, score = match
            tiers.append(tier)
            total += score
        if len(tiers) != len(tokens):
            continue
        ranked.append(((max(tiers), -total, pos), candidate))
    ranked.sort(key=lambda item: item[0])
    return tuple(candidate for _key, candidate in ranked[:limit])


def _row_name(row: Mapping[str, Any]) -> str:
    for key in ("agent_name", "name", "cl_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


__all__ = [
    "ArchiveNameCandidate",
    "archive_name_loader_for_owner",
    "load_archive_name_candidates",
    "search_archive_name_candidates",
]
