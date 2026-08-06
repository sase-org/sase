"""Turn one resolved plan path into a ``sase plan show`` record."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.core.paths import shorten_path
from sase.sdd.plan_display import (
    PlanDisplayPhase,
    PlanFileMetadata,
    plan_file_metadata_from_content,
    unavailable_plan_metadata,
)
from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots
from sase.sdd.plan_tiers import parse_plan_frontmatter
from sase.sdd.plan_waves import plan_phase_waves

from .model import (
    PlanShowAmbiguityCandidate,
    PlanShowPhase,
    PlanShowPlan,
    PlanShowProposal,
    PlanShowProvenanceSection,
    PlanShowRecord,
    PlanShowSource,
    PlanShowTarget,
    PlanShowValidation,
)


def load_plan_show_record(
    path: Path,
    *,
    target: PlanShowTarget,
    roots: tuple[Path, ...],
    proposal: PlanShowProposal | None = None,
    bead: str | None = None,
) -> PlanShowRecord:
    """Build one immutable show record from a resolved plan path."""
    normalized = path.expanduser().resolve(strict=False)
    metadata, content = _load_metadata_and_content(normalized)
    frontmatter: dict[str, Any] = {}
    body = ""
    if content is not None:
        frontmatter, _ = parse_plan_frontmatter(content)
        body = _body_below_frontmatter(content)

    source = _classify_source(normalized, roots=roots)
    phases = tuple(_phase(phase) for phase in metadata.phases)
    plan = PlanShowPlan(
        reference=canonicalize_plan_reference_from_roots(normalized, roots=roots),
        path=str(normalized),
        relpath=_relpath(normalized, roots=roots, source=source),
        source=source,
        exists=metadata.exists,
        tier=metadata.authored_tier,
        status=_normalized_str(frontmatter.get("status")),
        title=metadata.title,
        goal=metadata.goal,
        created_at=_normalized_str(frontmatter.get("create_time")),
        frontmatter=frontmatter,
        body=body,
        validation=PlanShowValidation(
            ok=metadata.validation_ok,
            diagnostics=metadata.validation_diagnostics,
        ),
        provenance=tuple(
            PlanShowProvenanceSection(
                kind=section.kind.value,
                entries=section.entries,
                targets=section.targets,
                omitted=section.omitted,
            )
            for section in metadata.provenance
        ),
        phases=phases,
        waves=plan_phase_waves(phases) if phases else None,
    )
    return PlanShowRecord(target=target, plan=plan, proposal=proposal, bead=bead)


def load_ambiguity_candidate(
    path: Path, *, roots: tuple[Path, ...]
) -> PlanShowAmbiguityCandidate:
    """Build one lightweight candidate row for an ambiguous target."""
    normalized = path.expanduser().resolve(strict=False)
    metadata, content = _load_metadata_and_content(normalized)
    frontmatter: dict[str, Any] = {}
    if content is not None:
        frontmatter, _ = parse_plan_frontmatter(content)
    reference = canonicalize_plan_reference_from_roots(normalized, roots=roots)
    return PlanShowAmbiguityCandidate(
        reference=reference or str(normalized),
        tier=metadata.authored_tier,
        created_at=_normalized_str(frontmatter.get("create_time")),
        title=metadata.title,
    )


def _load_metadata_and_content(path: Path) -> tuple[PlanFileMetadata, str | None]:
    """Read *path* at most once, returning display metadata plus raw content."""
    try:
        exists = path.is_file()
    except OSError:
        exists = False
    if not exists:
        return unavailable_plan_metadata(exists=False, readable=False), None
    try:
        readable = os.access(path, os.R_OK)
    except OSError as exc:
        return (
            unavailable_plan_metadata(
                exists=True, readable=False, diagnostics=(str(exc),)
            ),
            None,
        )
    if not readable:
        return unavailable_plan_metadata(exists=True, readable=False), None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            unavailable_plan_metadata(
                exists=True, readable=False, diagnostics=(str(exc),)
            ),
            None,
        )
    except UnicodeDecodeError as exc:
        return (
            unavailable_plan_metadata(
                exists=True, readable=True, diagnostics=(str(exc),)
            ),
            None,
        )
    return plan_file_metadata_from_content(content), content


def _body_below_frontmatter(content: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    return content[end + len("\n---\n") :]


def _classify_source(path: Path, *, roots: tuple[Path, ...]) -> PlanShowSource:
    if len(roots) >= 1 and _is_relative_to(path, roots[0]):
        return "repo"
    if len(roots) >= 2 and _is_relative_to(path, roots[1]):
        return "local"
    return "file"


def _relpath(path: Path, *, roots: tuple[Path, ...], source: PlanShowSource) -> str:
    if source == "repo":
        return path.relative_to(roots[0]).as_posix()
    if source == "local":
        return path.relative_to(roots[1]).as_posix()
    return shorten_path(str(path))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _phase(phase: PlanDisplayPhase) -> PlanShowPhase:
    return PlanShowPhase(
        id=phase.id,
        title=phase.title,
        depends_on=phase.depends_on,
        size=phase.size,
        model=phase.model,
        description=phase.description,
    )


def _normalized_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = ["load_ambiguity_candidate", "load_plan_show_record"]
