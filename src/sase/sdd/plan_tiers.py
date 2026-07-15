"""Shared helpers for canonical plan-file tiers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

PLAN_TIERS = ("tale", "epic")


def normalize_plan_tier(value: object) -> str | None:
    """Return a normalized supported plan-file tier, or ``None``."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in PLAN_TIERS else None


def _parse_plan_frontmatter(content: str) -> tuple[dict[str, Any], str | None]:
    """Parse YAML frontmatter best-effort, returning a parse error if invalid."""
    if not content.startswith("---\n"):
        return {}, None
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, "frontmatter closing marker not found"
    try:
        parsed = yaml.safe_load(content[4:end]) or {}
    except yaml.YAMLError as exc:
        return {}, f"invalid YAML frontmatter: {exc}"
    if not isinstance(parsed, dict):
        return {}, "frontmatter must be a YAML mapping"
    return dict(parsed), None


def read_plan_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read YAML frontmatter best-effort, returning a parse error if invalid."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, str(exc)
    return _parse_plan_frontmatter(content)


def read_plan_tier_from_content(content: str) -> str | None:
    """Read a valid explicit plan-file tier from in-memory content."""
    frontmatter, error = _parse_plan_frontmatter(content)
    if error is not None:
        return None
    return normalize_plan_tier(frontmatter.get("tier"))


def read_plan_tier(path: Path) -> str | None:
    """Read a valid explicit plan-file tier, returning ``None`` otherwise."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return read_plan_tier_from_content(content)


def classify_plan_file(path: Path, frontmatter: dict[str, Any] | None = None) -> str:
    """Classify a canonical plan, falling back to tale for best-effort reads."""
    if frontmatter is None:
        frontmatter, _ = read_plan_frontmatter(path)
    explicit = normalize_plan_tier(frontmatter.get("tier"))
    if explicit is not None:
        return explicit
    return "tale"
