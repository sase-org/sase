"""Deterministic planning for bead design-reference repairs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.bead.model import Issue
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_refs import (
    PLAN_REFERENCE_PREFIX,
    canonicalize_plan_reference_from_roots,
    parse_plan_reference,
    resolve_plan_reference_from_roots,
)


DesignRefUnrepairedReason = Literal[
    "no candidate",
    "ambiguous",
    "frontmatter names another bead",
]


@dataclass(frozen=True)
class _DesignRefRepair:
    """One event-backed bead design update proposed by the repair planner."""

    bead_id: str
    old_reference: str
    new_reference: str


@dataclass(frozen=True)
class _DesignRefUnrepaired:
    """One design reference that cannot be repaired safely."""

    bead_id: str
    old_reference: str
    reason: DesignRefUnrepairedReason


@dataclass(frozen=True)
class DesignRefRepairPreview:
    """Immutable repair and rejection set rendered before confirmation."""

    repairs: tuple[_DesignRefRepair, ...]
    unrepaired: tuple[_DesignRefUnrepaired, ...]


@dataclass(frozen=True)
class _PlanDocument:
    path: Path
    owner: str | None


@dataclass
class _RootPlanIndex:
    by_owner: dict[str, list[_PlanDocument]]
    by_basename: dict[str, list[_PlanDocument]]


def plan_design_ref_repairs(
    issues: list[Issue] | tuple[Issue, ...],
    *,
    roots: tuple[Path, ...],
) -> DesignRefRepairPreview:
    """Build a stable, read-only repair preview for *issues*."""

    normalized_roots = tuple(
        dict.fromkeys(root.expanduser().resolve(strict=False) for root in roots)
    )
    indexes = _build_root_indexes(normalized_roots)
    repairs: list[_DesignRefRepair] = []
    unrepaired: list[_DesignRefUnrepaired] = []

    for issue in issues:
        old_reference = issue.design.strip()
        if not old_reference:
            continue
        if _resolved_canonical_reference(old_reference, normalized_roots):
            continue

        basename = _reference_basename(old_reference)
        candidate, reason = _select_candidate(
            issue.id,
            basename,
            indexes,
        )
        if candidate is None:
            unrepaired.append(
                _DesignRefUnrepaired(
                    bead_id=issue.id,
                    old_reference=old_reference,
                    reason=reason,
                )
            )
            continue

        new_reference = canonicalize_plan_reference_from_roots(
            candidate.path,
            roots=normalized_roots,
        )
        if new_reference is None:
            unrepaired.append(
                _DesignRefUnrepaired(
                    bead_id=issue.id,
                    old_reference=old_reference,
                    reason="no candidate",
                )
            )
            continue
        if new_reference == old_reference:
            continue
        repairs.append(
            _DesignRefRepair(
                bead_id=issue.id,
                old_reference=old_reference,
                new_reference=new_reference,
            )
        )

    return DesignRefRepairPreview(
        repairs=tuple(repairs),
        unrepaired=tuple(unrepaired),
    )


def _build_root_indexes(roots: tuple[Path, ...]) -> tuple[_RootPlanIndex, ...]:
    seen_paths: set[Path] = set()
    indexes: list[_RootPlanIndex] = []
    for root in roots:
        by_owner: defaultdict[str, list[_PlanDocument]] = defaultdict(list)
        by_basename: defaultdict[str, list[_PlanDocument]] = defaultdict(list)
        for path in _iter_plan_documents(root):
            normalized = path.expanduser().resolve(strict=False)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            document = _PlanDocument(
                path=normalized,
                owner=_read_plan_owner(normalized),
            )
            if document.owner:
                by_owner[document.owner].append(document)
            by_basename[normalized.name].append(document)
        indexes.append(
            _RootPlanIndex(
                by_owner=dict(by_owner),
                by_basename=dict(by_basename),
            )
        )
    return tuple(indexes)


def _iter_plan_documents(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    paths = sorted(path for path in root.glob("*.md") if path.is_file())
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        paths.extend(sorted(path for path in child.glob("*.md") if path.is_file()))
    return tuple(paths)


def _read_plan_owner(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
    for field in ("bead_id", "bead"):
        raw = frontmatter.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _resolved_canonical_reference(
    value: str,
    roots: tuple[Path, ...],
) -> bool:
    try:
        parsed = parse_plan_reference(value)
    except (RuntimeError, ValueError):
        return False
    if parsed.legacy:
        return False
    try:
        resolution = resolve_plan_reference_from_roots(value, roots=roots)
    except (RuntimeError, ValueError):
        return False
    return resolution.status in {"exact", "drifted"}


def _reference_basename(value: str) -> str:
    try:
        raw_path = parse_plan_reference(value).path
    except (RuntimeError, ValueError):
        # "plans:" is immutable-history: stored bead design references may
        # still carry the legacy spelling. Accept it here too.
        raw_path = value.removeprefix(PLAN_REFERENCE_PREFIX).removeprefix("plans:")
    return Path(raw_path.replace("\\", "/")).name


def _select_candidate(
    bead_id: str,
    basename: str,
    indexes: tuple[_RootPlanIndex, ...],
) -> tuple[_PlanDocument | None, DesignRefUnrepairedReason]:
    for index in indexes:
        owner_matches = index.by_owner.get(bead_id, [])
        if len(owner_matches) > 1:
            return None, "ambiguous"
        if len(owner_matches) == 1:
            return owner_matches[0], "no candidate"

    if not basename:
        return None, "no candidate"
    for index in indexes:
        basename_matches = index.by_basename.get(basename, [])
        if len(basename_matches) > 1:
            return None, "ambiguous"
        if len(basename_matches) == 1:
            candidate = basename_matches[0]
            if candidate.owner is not None and candidate.owner != bead_id:
                return None, "frontmatter names another bead"
            return candidate, "no candidate"
    return None, "no candidate"


__all__ = [
    "DesignRefRepairPreview",
    "DesignRefUnrepairedReason",
    "plan_design_ref_repairs",
]
