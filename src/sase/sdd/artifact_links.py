"""Python adapter for the Rust-owned SDD artifact-link contract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sase.sdd.plan_header_block import (
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    render_plan_header_block,
    upsert_plan_header_section,
)


class SddArtifactLinkKind(StrEnum):
    """Representations recognized in one SDD Markdown document."""

    CANONICAL = "canonical"
    LEGACY = "legacy"
    MIXED = "mixed"
    MISSING = "missing"
    INVALID = "invalid"


class SddArtifactLinkType(StrEnum):
    """The counterpart named by an artifact-link bullet."""

    PLAN = "PLAN"
    PROMPT = "PROMPT"

    @property
    def legacy_field(self) -> str:
        return self.value.lower()


@dataclass(frozen=True)
class _SddLegacyArtifactLink:
    """One historical YAML-property link."""

    link_type: SddArtifactLinkType
    format: str
    reference: str
    target: str


@dataclass(frozen=True)
class SddArtifactLink:
    """Parsed artifact-link state with the clean user-authored body."""

    kind: SddArtifactLinkKind
    link_type: SddArtifactLinkType | None
    body: str
    label: str | None = None
    target: str | None = None
    legacy: _SddLegacyArtifactLink | None = None
    has_frontmatter: bool = False
    canonical_layout: bool = False
    reason: str | None = None

    @property
    def reference(self) -> str | None:
        """Return the stable visible path without choosing a conflict."""
        if self.kind is SddArtifactLinkKind.CANONICAL:
            return self.label
        if self.kind is SddArtifactLinkKind.LEGACY:
            return self.legacy.reference if self.legacy is not None else None
        if self.kind is SddArtifactLinkKind.MIXED and self.mixed_agrees:
            return self.label
        return None

    @property
    def resolution_target(self) -> str | None:
        """Return the preferred target without choosing a conflict."""
        if self.kind is SddArtifactLinkKind.CANONICAL:
            return self.target
        if self.kind is SddArtifactLinkKind.LEGACY:
            return self.legacy.target if self.legacy is not None else None
        if self.kind is SddArtifactLinkKind.MIXED and self.mixed_agrees:
            return self.target
        return None

    @property
    def mixed_agrees(self) -> bool:
        """Whether mixed representations plainly describe the same target."""
        if self.legacy is None or self.label is None or self.target is None:
            return False
        return self.legacy.reference == self.label or self.legacy.target == self.target


def parse_sdd_artifact_link(document: str) -> SddArtifactLink:
    """Parse canonical and historical links from a complete document."""
    parsed = parse_plan_header_block(document)
    counterparts = tuple(
        section
        for section in parsed.sections
        if section.kind in {PlanHeaderSectionKind.PLAN, PlanHeaderSectionKind.PROMPT}
    )
    canonical = counterparts[0] if counterparts else None
    legacy = None
    if parsed.legacy is not None:
        legacy = _SddLegacyArtifactLink(
            link_type=SddArtifactLinkType(parsed.legacy.kind.value),
            format=parsed.legacy.format,
            reference=parsed.legacy.reference,
            target=parsed.legacy.target,
        )
    link_type = (
        SddArtifactLinkType(canonical.kind.value)
        if canonical is not None
        else legacy.link_type
        if legacy is not None
        else None
    )
    if parsed.disposition.value == SddArtifactLinkKind.INVALID.value:
        kind = SddArtifactLinkKind.INVALID
    elif canonical is not None and legacy is not None:
        kind = SddArtifactLinkKind.MIXED
    elif canonical is not None:
        kind = SddArtifactLinkKind.CANONICAL
    elif legacy is not None:
        kind = SddArtifactLinkKind.LEGACY
    else:
        kind = SddArtifactLinkKind.MISSING
    return SddArtifactLink(
        kind=kind,
        link_type=link_type,
        body=parsed.body,
        label=canonical.label if canonical is not None else None,
        target=canonical.target if canonical is not None else None,
        legacy=legacy,
        has_frontmatter=parsed.has_frontmatter,
        canonical_layout=parsed.canonical_layout,
        reason=parsed.reason,
    )


def _render_sdd_artifact_link(
    link_type: SddArtifactLinkType, label: str, target: str
) -> str:
    """Render one exact canonical Markdown bullet."""
    return render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind(link_type.value),
                label=label,
                target=target,
            ),
        )
    )


def _update_sdd_artifact_link(
    document: str,
    link_type: SddArtifactLinkType,
    label: str,
    target: str | None,
    *,
    remove_legacy: bool = True,
    allow_resolved_mixed: bool = False,
) -> str:
    """Install a canonical bullet through the shared document updater."""
    return upsert_plan_header_section(
        document,
        PlanHeaderSection(
            kind=PlanHeaderSectionKind(link_type.value),
            label=label,
            target=target,
        ),
        remove_legacy=remove_legacy,
        allow_resolved_mixed=allow_resolved_mixed,
    )


def stable_sdd_reference(sdd_dir: Path, path: Path) -> str:
    """Return the storage-layout-aware stable label for an SDD artifact."""
    relative = path.relative_to(sdd_dir).as_posix()
    if sdd_dir.name == "sdd" and sdd_dir.parent.name == ".sase":
        return f".sase/sdd/{relative}"
    if sdd_dir.name == "sdd":
        return f"sdd/{relative}"
    return relative


def canonical_sdd_artifact_link(
    sdd_dir: Path,
    source: Path,
    target: Path,
    link_type: SddArtifactLinkType,
    *,
    label_prefix: str = "",
) -> tuple[str, str, str]:
    """Return ``(label, href, bullet)`` for two physical artifact paths."""
    label = f"{label_prefix}{stable_sdd_reference(sdd_dir, target)}"
    source_parent = source.parent.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    href = Path(os.path.relpath(resolved_target, source_parent)).as_posix()
    return label, href, _render_sdd_artifact_link(link_type, label, href)


def update_source_aware_artifact_link(
    document: str,
    sdd_dir: Path,
    source: Path,
    target: Path | None,
    link_type: SddArtifactLinkType,
    *,
    label_prefix: str = "",
    target_label: str | None = None,
    target_href: str | None = None,
    remove_legacy: bool = True,
) -> str:
    """Install a source-aware local or cross-repository artifact link.

    Local links pass *target* and derive both the stable label and relative
    href from its path. Cross-repository links pass ``target=None`` together
    with an explicit *target_label* and hosted *target_href*. Keeping both
    forms behind this updater preserves one parser, conflict check, and
    legacy-removal path for reciprocal plan/prompt links.
    """
    parsed = parse_sdd_artifact_link(document)
    allow_resolved_mixed = False
    if parsed.kind is SddArtifactLinkKind.MIXED:
        if not _mixed_representations_agree(parsed, sdd_dir, source):
            raise ValueError(
                "canonical and legacy artifact links resolve to different targets"
            )
        allow_resolved_mixed = True
    cross_repository = target_label is not None or target_href is not None
    if cross_repository:
        if target is not None:
            raise ValueError(
                "cross-repository artifact links cannot also name a local target"
            )
        if not target_label:
            raise ValueError("cross-repository artifact links require a label")
        label = target_label
        href = target_href
    else:
        if target is None:
            raise ValueError("local artifact links require a target path")
        label, href, _ = canonical_sdd_artifact_link(
            sdd_dir,
            source,
            target,
            link_type,
            label_prefix=label_prefix,
        )
    return _update_sdd_artifact_link(
        document,
        link_type,
        label,
        href,
        remove_legacy=remove_legacy,
        allow_resolved_mixed=allow_resolved_mixed,
    )


def update_cross_repository_artifact_link(
    document: str,
    link_type: SddArtifactLinkType,
    *,
    label: str,
    href: str,
    remove_legacy: bool = True,
) -> str:
    """Install a hosted counterpart through the source-aware updater."""

    return update_source_aware_artifact_link(
        document,
        Path("."),
        Path("prompt.md"),
        None,
        link_type,
        target_label=label,
        target_href=href,
        remove_legacy=remove_legacy,
    )


def _mixed_representations_agree(
    link: SddArtifactLink, sdd_dir: Path, source: Path
) -> bool:
    if link.target is None or link.legacy is None:
        return False
    canonical = (source.parent / link.target).resolve(strict=False)
    if link.legacy.format == "markdown":
        legacy = (source.parent / link.legacy.target).resolve(strict=False)
    else:
        target = Path(link.legacy.target)
        candidates = [
            sdd_dir / target,
            sdd_dir.parent / target,
            sdd_dir.parent.parent / target,
            Path.cwd() / target,
        ]
        legacy = next(
            (
                candidate.resolve(strict=False)
                for candidate in candidates
                if candidate.exists()
            ),
            candidates[0].resolve(strict=False),
        )
    return canonical == legacy


__all__ = [
    "SddArtifactLink",
    "SddArtifactLinkKind",
    "SddArtifactLinkType",
    "canonical_sdd_artifact_link",
    "parse_sdd_artifact_link",
    "stable_sdd_reference",
    "update_cross_repository_artifact_link",
    "update_source_aware_artifact_link",
]
