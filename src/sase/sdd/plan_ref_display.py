"""Shared presentation of a plan reference and where it currently resolves.

Every surface that shows a bead's plan link renders the stable reference first
and where it resolves second, and says plainly when it resolves nowhere. The
wording here mirrors ``display_design_path`` in the Rust CLI renderer
(``crates/sase_core/src/bead/cli.rs``); change both together.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from sase.sdd.plan_refs import (
    PlanReferenceResolution,
    parse_plan_reference,
    resolve_plan_reference_from_roots,
)


PLAN_REFERENCE_MISSING_LABEL = "(unresolved: no plan file found)"
PLAN_REFERENCE_AMBIGUOUS_LABEL = "(ambiguous: multiple plans match this reference)"
PLAN_REFERENCE_INVALID_LABEL = "(unresolved: malformed plan reference)"
PLAN_REFERENCE_DRIFT_SUFFIX = " (month drift)"
PLAN_REFERENCE_ARROW = "→"

_UNRESOLVED_LABELS = {
    "ambiguous": PLAN_REFERENCE_AMBIGUOUS_LABEL,
    "invalid": PLAN_REFERENCE_INVALID_LABEL,
    "missing": PLAN_REFERENCE_MISSING_LABEL,
}


@dataclass(frozen=True)
class PlanReferenceDisplay:
    """One reference, where it resolves, and how to say so."""

    reference: str
    resolved_path: str | None
    detail: str
    status: str

    @property
    def resolved(self) -> bool:
        """Return whether the reference names a plan file that exists."""

        return self.resolved_path is not None

    @property
    def lines(self) -> tuple[str, ...]:
        """Return the reference line and its resolution line, deduplicated."""

        if self.resolved and self.detail == self.reference:
            return (self.reference,)
        return (self.reference, f"{PLAN_REFERENCE_ARROW} {self.detail}")


def _plan_reference_display(
    reference: str,
    *,
    resolved_path: str | Path | None,
    status: str = "exact",
    relative_to: Path | None = None,
) -> PlanReferenceDisplay:
    """Describe *reference* against an already-resolved path or failure."""

    if resolved_path is None:
        label = _UNRESOLVED_LABELS.get(status, PLAN_REFERENCE_MISSING_LABEL)
        return PlanReferenceDisplay(reference, None, label, status)

    display = str(resolved_path)
    if relative_to is not None:
        display = _relativize(display, relative_to)
    if status == "drifted":
        display += PLAN_REFERENCE_DRIFT_SUFFIX
    return PlanReferenceDisplay(reference, str(resolved_path), display, status)


def describe_design_reference(
    design: str,
    *,
    roots: tuple[Path, ...],
    cwd: Path,
    relativize: bool = False,
) -> PlanReferenceDisplay:
    """Resolve a stored ``design`` value and describe where it points."""

    resolution = _resolve(design, roots)
    if resolution is None:
        return _plan_reference_display(design, resolved_path=None, status="invalid")

    resolved_path = resolution.resolved_path
    status = resolution.status
    if resolved_path is None and (fallback := _legacy_path_below(design, cwd)):
        resolved_path, status = fallback, "exact"
    if resolved_path is None:
        return _plan_reference_display(design, resolved_path=None, status=status)
    return _plan_reference_display(
        design,
        resolved_path=resolved_path,
        status=status,
        relative_to=cwd if relativize else None,
    )


def _resolve(
    design: str,
    roots: tuple[Path, ...],
) -> PlanReferenceResolution | None:
    try:
        return resolve_plan_reference_from_roots(design, roots=roots)
    except (OSError, RuntimeError, ValueError):
        return None


def _legacy_path_below(design: str, cwd: Path) -> Path | None:
    """Keep resolving in-tree links stored as workspace-relative paths."""

    try:
        parsed = parse_plan_reference(design)
    except (OSError, RuntimeError, ValueError):
        return None
    raw = Path(design).expanduser()
    if not parsed.legacy or raw.is_absolute():
        return None
    try:
        candidate = (cwd / raw).resolve(strict=False)
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def _relativize(path: str, root: Path) -> str:
    try:
        return os.path.relpath(path, root)
    except (OSError, ValueError):
        return path


__all__ = [
    "PLAN_REFERENCE_AMBIGUOUS_LABEL",
    "PLAN_REFERENCE_ARROW",
    "PLAN_REFERENCE_DRIFT_SUFFIX",
    "PLAN_REFERENCE_INVALID_LABEL",
    "PLAN_REFERENCE_MISSING_LABEL",
    "PlanReferenceDisplay",
    "describe_design_reference",
]
