"""Bounded caches used by associated-plan resolution."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter
from sase.sdd.plan_validate import PlanValidationResult, ValidatedPlanPhase

from ._agent_associated_plan_types import (
    AssociatedPlanPhaseAvailability,
    AssociatedPlanPhaseSummary,
    AuthoredPlanTier,
    PlanAssociationCacheKey,
    PlanFileSignature,
    PlanFileCacheEntry,
    PlanFileMetadata,
    ResolvedPlanAssociation,
)

_CACHE_MAX_ENTRIES = 256
_ASSOCIATION_TTL_SECONDS = 60.0
_NEGATIVE_TTL_SECONDS = 5.0
_CACHE_MISS: Final = object()

_ReadableCheck = Callable[[Path], bool]
_PlanValidator = Callable[[str, str], PlanValidationResult]


class PlanFileCache:
    """Bounded frontmatter cache invalidated by file mtime and size."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[Path, PlanFileCacheEntry] = OrderedDict()
        self._lock = RLock()

    def get(
        self,
        path: Path,
        *,
        is_readable: _ReadableCheck,
        validate: _PlanValidator,
    ) -> PlanFileMetadata:
        normalized = path.expanduser().resolve(strict=False)
        now = monotonic()
        try:
            stat = normalized.stat()
            signature: PlanFileSignature | None = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None

        with self._lock:
            entry = self._entries.get(normalized)
            if entry is not None:
                self._entries.move_to_end(normalized)
                if signature is not None and entry.signature == signature:
                    return entry.metadata
                if (
                    signature is None
                    and entry.signature is None
                    and entry.expires_at is not None
                    and entry.expires_at > now
                ):
                    return entry.metadata

            metadata = self._load(
                normalized,
                exists=signature is not None,
                is_readable=is_readable,
                validate=validate,
            )
            result = PlanFileCacheEntry(
                signature=signature,
                metadata=metadata,
                expires_at=(now + _NEGATIVE_TTL_SECONDS if signature is None else None),
            )
            self._entries[normalized] = result
            self._entries.move_to_end(normalized)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return metadata

    @staticmethod
    def _load(
        path: Path,
        *,
        exists: bool,
        is_readable: _ReadableCheck,
        validate: _PlanValidator,
    ) -> PlanFileMetadata:
        if not exists:
            return _unavailable_metadata(exists=False, readable=False)

        if not is_readable(path):
            return _unavailable_metadata(exists=True, readable=False)

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return _unavailable_metadata(exists=True, readable=False)
        except UnicodeDecodeError:
            return _unavailable_metadata(exists=True, readable=True)

        frontmatter, error = parse_plan_frontmatter(content)
        if error is not None:
            return _unavailable_metadata(exists=True, readable=True)

        raw_title = frontmatter.get("title")
        title = " ".join(raw_title.split()) if isinstance(raw_title, str) else None
        raw_goal = frontmatter.get("goal")
        goal = " ".join(raw_goal.split()) if isinstance(raw_goal, str) else None
        normalized_tier = normalize_plan_tier(frontmatter.get("tier"))
        authored_tier: AuthoredPlanTier | None = None
        if normalized_tier == "tale":
            authored_tier = "tale"
        elif normalized_tier == "epic":
            authored_tier = "epic"

        phase_availability: AssociatedPlanPhaseAvailability = "not-applicable"
        phases: tuple[AssociatedPlanPhaseSummary, ...] = ()
        if authored_tier == "epic":
            phase_availability = "unavailable"
            try:
                validation = validate(content, "epic")
            except Exception:
                validation = None
            if validation is not None and validation.ok and validation.plan is not None:
                phases = tuple(
                    _phase_summary(phase) for phase in validation.plan.phases
                )
                phase_availability = "available"
        return PlanFileMetadata(
            title=title or None,
            goal=goal or None,
            authored_tier=authored_tier,
            exists=True,
            readable=True,
            frontmatter_readable=True,
            phase_availability=phase_availability,
            phases=phases,
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class PlanAssociationCache:
    """Short-lived cache for direct and bead-derived plan resolution."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[
            PlanAssociationCacheKey, tuple[float, ResolvedPlanAssociation]
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: PlanAssociationCacheKey) -> ResolvedPlanAssociation | object:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return _CACHE_MISS
            expires_at, association = entry
            if expires_at <= now:
                del self._entries[key]
                return _CACHE_MISS
            self._entries.move_to_end(key)
            return association

    def set(
        self,
        key: PlanAssociationCacheKey,
        association: ResolvedPlanAssociation,
    ) -> None:
        ttl = (
            _NEGATIVE_TTL_SECONDS
            if association.path is None
            else _ASSOCIATION_TTL_SECONDS
        )
        with self._lock:
            self._entries[key] = (monotonic() + ttl, association)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _unavailable_metadata(*, exists: bool, readable: bool) -> PlanFileMetadata:
    return PlanFileMetadata(
        title=None,
        goal=None,
        authored_tier=None,
        exists=exists,
        readable=readable,
        frontmatter_readable=False,
        phase_availability="unavailable",
        phases=(),
    )


def _phase_summary(phase: ValidatedPlanPhase) -> AssociatedPlanPhaseSummary:
    return AssociatedPlanPhaseSummary(
        id=phase.id,
        title=phase.title,
        depends_on=phase.depends_on,
        description=phase.description,
        model=phase.model,
    )


_PLAN_FILE_CACHE = PlanFileCache()
_PLAN_ASSOCIATION_CACHE = PlanAssociationCache()
