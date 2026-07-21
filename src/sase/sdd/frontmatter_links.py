"""Python adapter for the Rust-owned SDD frontmatter-link contract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding


class SddFrontmatterLinkKind(StrEnum):
    """Supported classifications for one prompt/plan link value."""

    CANONICAL = "canonical"
    LEGACY = "legacy"
    INVALID = "invalid"


@dataclass(frozen=True)
class SddFrontmatterLink:
    """Parsed prompt/plan frontmatter value with raw input retained."""

    kind: SddFrontmatterLinkKind
    raw: str
    label: str | None = None
    target: str | None = None
    path: str | None = None
    reason: str | None = None

    @property
    def reference(self) -> str:
        """Return the stable path-like value expected by existing models."""
        if self.kind is SddFrontmatterLinkKind.CANONICAL:
            return self.label or self.raw
        if self.kind is SddFrontmatterLinkKind.LEGACY:
            return self.path or self.raw
        return self.raw

    @property
    def resolution_target(self) -> str | None:
        """Return the path component callers may safely resolve."""
        if self.kind is SddFrontmatterLinkKind.CANONICAL:
            return self.target
        if self.kind is SddFrontmatterLinkKind.LEGACY:
            return self.path
        return None


def parse_sdd_frontmatter_link(value: str) -> SddFrontmatterLink:
    """Parse canonical Markdown or classify a historical plain-path value."""
    binding = require_rust_binding("sdd_frontmatter_link_parse")
    payload = dict(binding(value))
    kind = SddFrontmatterLinkKind(str(payload["kind"]))
    return SddFrontmatterLink(
        kind=kind,
        raw=value,
        label=_optional_str(payload, "label"),
        target=_optional_str(payload, "target"),
        path=_optional_str(payload, "path"),
        reason=_optional_str(payload, "reason"),
    )


def _render_sdd_frontmatter_link(label: str, target: str) -> str:
    """Render one canonical clickable frontmatter link."""
    binding = require_rust_binding("sdd_frontmatter_link_render")
    return str(binding(label, target))


def stable_sdd_reference(sdd_dir: Path, path: Path) -> str:
    """Return the storage-layout-aware stable label for an SDD artifact."""
    relative = path.relative_to(sdd_dir).as_posix()
    if sdd_dir.name == "sdd" and sdd_dir.parent.name == ".sase":
        return f".sase/sdd/{relative}"
    if sdd_dir.name == "sdd":
        return f"sdd/{relative}"
    return relative


def canonical_sdd_frontmatter_link(
    sdd_dir: Path,
    source: Path,
    target: Path,
    *,
    label_prefix: str = "",
) -> str:
    """Build a canonical link from stable label and physical file locations."""
    label = f"{label_prefix}{stable_sdd_reference(sdd_dir, target)}"
    source_parent = source.parent.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    href = Path(os.path.relpath(resolved_target, source_parent)).as_posix()
    return _render_sdd_frontmatter_link(label, href)


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


__all__ = [
    "SddFrontmatterLink",
    "SddFrontmatterLinkKind",
    "canonical_sdd_frontmatter_link",
    "parse_sdd_frontmatter_link",
    "stable_sdd_reference",
]
