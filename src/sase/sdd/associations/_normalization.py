"""Canonical plan-reference and agent-name normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.sdd.plan_refs import (
    PLAN_REFERENCE_KIND,
    PLAN_REFERENCE_PREFIX,
    canonicalize_plan_reference_from_roots,
    parse_plan_reference,
    resolve_plan_reference_from_roots,
)
from sase.sdd.store import SddStore

_LEGACY_PLAN_PREFIXES = (
    ".sase/sdd/plans/",
    "sase/repos/plans/",
    "sdd/plans/",
    "plans/",
)


@dataclass(frozen=True, slots=True)
class PlanReferenceNormalizer:
    """Collapse persisted plan spellings onto one ``plan:`` key."""

    store: SddStore
    primary_root: Path

    @property
    def roots(self) -> tuple[Path, ...]:
        return (self.store.kind_root("plans").resolve(strict=False),)

    def normalize(self, value: str | Path | None) -> str | None:
        """Return one canonical logical plan reference."""

        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = parse_plan_reference(raw)
        except (ImportError, RuntimeError, TypeError, ValueError):
            parsed = None
        if parsed is not None and not parsed.legacy:
            return parsed.rendered if parsed.kind == PLAN_REFERENCE_KIND else None

        path = Path(raw).expanduser()
        if path.is_absolute():
            canonical = canonicalize_plan_reference_from_roots(
                path,
                roots=self.roots,
            )
            if canonical is not None:
                return canonical
            return _canonical_legacy_suffix(path.as_posix())

        resolved = self._resolve_existing(raw)
        if resolved is not None:
            return resolved
        normalized = path.as_posix().removeprefix("./")
        legacy = _canonical_legacy_suffix(normalized)
        if legacy is not None:
            return legacy
        if not normalized or normalized.startswith("../"):
            return None
        return f"{PLAN_REFERENCE_PREFIX}{normalized}"

    def _resolve_existing(self, raw: str) -> str | None:
        try:
            resolution = resolve_plan_reference_from_roots(raw, roots=self.roots)
        except (ImportError, RuntimeError, TypeError, ValueError):
            return None
        if resolution.resolved_path is None:
            return None
        return canonicalize_plan_reference_from_roots(
            resolution.resolved_path,
            roots=self.roots,
        )


def _canonical_legacy_suffix(value: str) -> str | None:
    normalized = value.removeprefix("./")
    for prefix in _LEGACY_PLAN_PREFIXES:
        marker = prefix if normalized.startswith(prefix) else f"/{prefix}"
        if marker not in normalized:
            continue
        suffix = normalized.split(marker, 1)[1]
        return f"{PLAN_REFERENCE_PREFIX}{suffix}" if suffix else None
    return None


__all__ = ["PlanReferenceNormalizer"]
