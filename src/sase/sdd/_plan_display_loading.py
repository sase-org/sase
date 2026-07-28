"""Filesystem loading and validation for shared plan-display values."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Protocol

from sase.phase_size_presentation import normalize_phase_size
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter
from sase.sdd.plan_validate import (
    PlanValidationResult,
    ValidatedPlanPhase,
    validate_plan,
)

from ._plan_display_models import (
    AuthoredPlanTier,
    PlanDisplay,
    PlanDisplayPhase,
    PlanDisplayTier,
    PlanFileMetadata,
    PlanPhaseAvailability,
    PlanProvenanceSection,
)

_PROVENANCE_ROW_ORDER: tuple[PlanHeaderSectionKind, ...] = (
    PlanHeaderSectionKind.PLAN,
    PlanHeaderSectionKind.PROMPT,
    PlanHeaderSectionKind.PARENT,
    PlanHeaderSectionKind.AGENTS,
    PlanHeaderSectionKind.COMMITS,
)


class _PlanValidator(Protocol):
    def __call__(
        self,
        content: str,
        tier: str,
        *,
        mode: str = "authoring",
    ) -> PlanValidationResult: ...


def load_plan_display(
    path: str | Path,
    *,
    display_path: str | None = None,
    effective_tier: PlanDisplayTier | None = None,
    committed: bool | None = None,
    is_readable: Callable[[Path], bool] | None = None,
    validate: _PlanValidator = validate_plan,
) -> PlanDisplay:
    """Load one plan without raising for missing, unreadable, or invalid input."""
    try:
        normalized = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        normalized = Path(str(path))
        metadata = unavailable_plan_metadata(
            exists=False,
            readable=False,
            diagnostics=(str(exc),),
        )
    else:
        metadata = _load_plan_file_metadata(
            normalized,
            is_readable=is_readable,
            validate=validate,
        )
    return PlanDisplay(
        title=metadata.title,
        goal=metadata.goal,
        authored_tier=metadata.authored_tier,
        effective_tier=effective_tier or metadata.authored_tier,
        actual_path=str(normalized),
        display_path=display_path or str(path),
        committed=committed,
        exists=metadata.exists,
        readable=metadata.readable,
        frontmatter_readable=metadata.frontmatter_readable,
        phase_availability=metadata.phase_availability,
        phases=metadata.phases,
        validation_ok=metadata.validation_ok,
        validation_diagnostics=metadata.validation_diagnostics,
        provenance=metadata.provenance,
    )


def _load_plan_file_metadata(
    path: Path,
    *,
    is_readable: Callable[[Path], bool] | None = None,
    validate: _PlanValidator = validate_plan,
) -> PlanFileMetadata:
    """Read and normalize one plan file into display metadata."""
    readable_check = is_readable or (lambda candidate: os.access(candidate, os.R_OK))
    try:
        exists = path.is_file()
    except OSError:
        exists = False
    if not exists:
        return unavailable_plan_metadata(exists=False, readable=False)
    try:
        readable = readable_check(path)
    except (OSError, RuntimeError, ValueError) as exc:
        return unavailable_plan_metadata(
            exists=True,
            readable=False,
            diagnostics=(str(exc),),
        )
    if not readable:
        return unavailable_plan_metadata(exists=True, readable=False)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return unavailable_plan_metadata(
            exists=True,
            readable=False,
            diagnostics=(str(exc),),
        )
    except UnicodeDecodeError as exc:
        return unavailable_plan_metadata(
            exists=True,
            readable=True,
            diagnostics=(str(exc),),
        )
    return plan_file_metadata_from_content(content, validate=validate)


def plan_file_metadata_from_content(
    content: str,
    *,
    validate: _PlanValidator = validate_plan,
) -> PlanFileMetadata:
    """Normalize already-read plan content using launch-mode validation."""
    frontmatter, error = parse_plan_frontmatter(content)
    if error is not None:
        return unavailable_plan_metadata(
            exists=True,
            readable=True,
            diagnostics=(error,),
        )

    title = _normalized_optional_text(frontmatter.get("title"))
    goal = _normalized_optional_text(frontmatter.get("goal"))
    normalized_tier = normalize_plan_tier(frontmatter.get("tier"))
    authored_tier: AuthoredPlanTier | None = None
    if normalized_tier == "tale":
        authored_tier = "tale"
    elif normalized_tier == "epic":
        authored_tier = "epic"

    phase_availability: PlanPhaseAvailability = "not-applicable"
    phases: tuple[PlanDisplayPhase, ...] = ()
    validation_ok = False
    diagnostics: tuple[str, ...] = ()
    if authored_tier is None:
        diagnostics = ("plan frontmatter has no valid tale or epic tier",)
    else:
        if authored_tier == "epic":
            phase_availability = "unavailable"
        try:
            validation = validate(content, authored_tier, mode="launch")
        except Exception as exc:
            diagnostics = (str(exc),)
        else:
            validation_ok = validation.ok and validation.plan is not None
            diagnostics = tuple(
                diagnostic.message for diagnostic in validation.diagnostics
            )
            if validation_ok:
                assert validation.plan is not None
                title = _normalized_optional_text(validation.plan.title)
                goal = _normalized_optional_text(validation.plan.goal)
                if authored_tier == "epic":
                    try:
                        phases = tuple(
                            _plan_display_phase(phase)
                            for phase in validation.plan.phases
                        )
                    except (TypeError, ValueError) as exc:
                        validation_ok = False
                        diagnostics = (*diagnostics, str(exc))
                        phases = ()
                    else:
                        phase_availability = "available"

    return PlanFileMetadata(
        title=title,
        goal=goal,
        authored_tier=authored_tier,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability=phase_availability,
        phases=phases,
        validation_ok=validation_ok,
        validation_diagnostics=diagnostics,
        provenance=_plan_provenance_sections(content),
    )


def _plan_provenance_sections(content: str) -> tuple[PlanProvenanceSection, ...]:
    """Reduce one document's plan-header block to display-ready sections.

    A malformed or unparseable header block yields no sections rather than
    raising: the provenance header is a projection, and the plan's authored
    metadata must stay visible even when that projection is broken.
    """
    try:
        document = parse_plan_header_block(content)
    except Exception:
        return ()
    sections: list[PlanProvenanceSection] = []
    for section in document.sections:
        if section.entries:
            entries = tuple(entry.label for entry in section.entries)
        elif section.label:
            entries = (section.label,)
        else:
            continue
        sections.append(
            PlanProvenanceSection(
                kind=section.kind,
                entries=entries,
                omitted=max(section.omitted, 0),
            )
        )
    sections.sort(key=lambda section: _PROVENANCE_ROW_ORDER.index(section.kind))
    return tuple(sections)


def unavailable_plan_metadata(
    *,
    exists: bool,
    readable: bool,
    diagnostics: tuple[str, ...] = (),
) -> PlanFileMetadata:
    """Return an honest metadata value for an unavailable plan."""
    return PlanFileMetadata(
        title=None,
        goal=None,
        authored_tier=None,
        exists=exists,
        readable=readable,
        frontmatter_readable=False,
        phase_availability="unavailable",
        phases=(),
        validation_diagnostics=diagnostics,
    )


def _plan_display_phase(phase: ValidatedPlanPhase) -> PlanDisplayPhase:
    """Convert one authoritative validator phase to a display value."""
    size = normalize_phase_size(phase.size)
    if size is None:
        raise ValueError(f"validator returned invalid phase size: {phase.size!r}")
    return PlanDisplayPhase(
        id=phase.id,
        title=" ".join(phase.title.split()),
        depends_on=phase.depends_on,
        description=phase.description,
        size=size,
        model=phase.model,
    )


def _normalized_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


__all__ = [
    "load_plan_display",
    "plan_file_metadata_from_content",
    "unavailable_plan_metadata",
]
