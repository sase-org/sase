"""Python adapter for the Rust-owned SDD artifact-link contract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding


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
    binding = require_rust_binding("sdd_artifact_link_parse")
    payload = dict(binding(document))
    legacy_payload = payload.get("legacy")
    legacy = None
    if isinstance(legacy_payload, dict):
        legacy = _SddLegacyArtifactLink(
            link_type=SddArtifactLinkType(str(legacy_payload["link_type"])),
            format=str(legacy_payload["format"]),
            reference=str(legacy_payload["reference"]),
            target=str(legacy_payload["target"]),
        )
    link_type = _optional_str(payload, "link_type")
    return SddArtifactLink(
        kind=SddArtifactLinkKind(str(payload["kind"])),
        link_type=SddArtifactLinkType(link_type) if link_type is not None else None,
        body=str(payload.get("body") or ""),
        label=_optional_str(payload, "label"),
        target=_optional_str(payload, "target"),
        legacy=legacy,
        has_frontmatter=bool(payload.get("has_frontmatter")),
        canonical_layout=bool(payload.get("canonical_layout")),
        reason=_optional_str(payload, "reason"),
    )


def _render_sdd_artifact_link(
    link_type: SddArtifactLinkType, label: str, target: str
) -> str:
    """Render one exact canonical Markdown bullet."""
    binding = require_rust_binding("sdd_artifact_link_render")
    return str(binding(link_type.value, label, target))


def _update_sdd_artifact_link(
    document: str,
    link_type: SddArtifactLinkType,
    label: str,
    target: str,
    *,
    remove_legacy: bool = True,
    allow_resolved_mixed: bool = False,
) -> str:
    """Install a canonical bullet through the shared document updater."""
    binding = require_rust_binding("sdd_artifact_link_upsert")
    return str(
        binding(
            document,
            link_type.value,
            label,
            target,
            remove_legacy,
            allow_resolved_mixed,
        )
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
    target: Path,
    link_type: SddArtifactLinkType,
    *,
    label_prefix: str = "",
    remove_legacy: bool = True,
) -> str:
    """Compute a file-relative link and install it in one document."""
    parsed = parse_sdd_artifact_link(document)
    allow_resolved_mixed = False
    if parsed.kind is SddArtifactLinkKind.MIXED:
        if not _mixed_representations_agree(parsed, sdd_dir, source):
            raise ValueError(
                "canonical and legacy artifact links resolve to different targets"
            )
        allow_resolved_mixed = True
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


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


__all__ = [
    "SddArtifactLink",
    "SddArtifactLinkKind",
    "SddArtifactLinkType",
    "canonical_sdd_artifact_link",
    "parse_sdd_artifact_link",
    "stable_sdd_reference",
    "update_source_aware_artifact_link",
]
