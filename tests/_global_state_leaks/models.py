"""Internal value objects used by the global-state leak detector."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class _ValueFingerprint:
    kind: str
    length: int | None
    digest: str
    preview: str
    entries: frozenset[str] = frozenset()
    sequence: tuple[str, ...] = ()

    def public(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "digest": self.digest,
            "preview": self.preview,
        }
        if self.length is not None:
            payload["len"] = self.length
        return payload


@dataclass(frozen=True)
class _CacheFingerprint:
    hits: int
    misses: int
    maxsize: int | None
    currsize: int

    def public(self) -> dict[str, int | None]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "maxsize": self.maxsize,
            "currsize": self.currsize,
        }


@dataclass(frozen=True)
class _Snapshot:
    globals: Mapping[str, _ValueFingerprint]
    caches: Mapping[str, _CacheFingerprint]
    environ: _ValueFingerprint
    sys_path: _ValueFingerprint
    cwd: str


@dataclass(frozen=True)
class _Change:
    kind: str
    name: str
    reason: str
    before: dict[str, object]
    after: dict[str, object]
    details: Mapping[str, object] | None = None

    def public(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "name": self.name,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class _Diff:
    poisoning: tuple[_Change, ...]
    warming_counts: Mapping[str, int]
    cooling_counts: Mapping[str, int]
    invalidation_counts: Mapping[str, int]

    @property
    def warming_count(self) -> int:
        return sum(self.warming_counts.values())

    @property
    def cooling_count(self) -> int:
        return sum(self.cooling_counts.values())

    @property
    def invalidation_count(self) -> int:
        return sum(self.invalidation_counts.values())
