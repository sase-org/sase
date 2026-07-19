"""Shared helpers for canonical plan-file tiers."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

import yaml  # type: ignore[import-untyped]

PLAN_TIERS = ("tale", "epic")
_PLAN_TIER_CACHE_MAX_ENTRIES = 256
_NEGATIVE_PLAN_TIER_TTL_SECONDS = 5.0
_PlanFileSignature = tuple[int, int]
_PlanTierCacheEntry = tuple[_PlanFileSignature | None, str | None, float | None]
_PLAN_TIER_CACHE: OrderedDict[Path, _PlanTierCacheEntry] = OrderedDict()
_PLAN_TIER_CACHE_LOCK = RLock()


def normalize_plan_tier(value: object) -> str | None:
    """Return a normalized supported plan-file tier, or ``None``."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in PLAN_TIERS else None


def parse_plan_frontmatter(content: str) -> tuple[dict[str, Any], str | None]:
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


def _read_plan_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read YAML frontmatter best-effort, returning a parse error if invalid."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, str(exc)
    return parse_plan_frontmatter(content)


def read_plan_tier_from_content(content: str) -> str | None:
    """Read a valid explicit plan-file tier from in-memory content."""
    frontmatter, error = parse_plan_frontmatter(content)
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


def cached_plan_tier(path: str | Path | None) -> str | None:
    """Read a plan tier through a bounded, file-signature-aware cache."""
    if path is None:
        return None
    try:
        normalized = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    try:
        stat = normalized.stat()
        signature: _PlanFileSignature | None = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        signature = None

    now = monotonic()
    with _PLAN_TIER_CACHE_LOCK:
        entry = _PLAN_TIER_CACHE.get(normalized)
        if entry is not None:
            cached_signature, cached_tier, expires_at = entry
            if cached_signature == signature and (
                expires_at is None or expires_at > now
            ):
                _PLAN_TIER_CACHE.move_to_end(normalized)
                return cached_tier

    tier = read_plan_tier(normalized) if signature is not None else None
    expires_at = now + _NEGATIVE_PLAN_TIER_TTL_SECONDS if tier is None else None
    with _PLAN_TIER_CACHE_LOCK:
        _PLAN_TIER_CACHE[normalized] = (signature, tier, expires_at)
        _PLAN_TIER_CACHE.move_to_end(normalized)
        while len(_PLAN_TIER_CACHE) > _PLAN_TIER_CACHE_MAX_ENTRIES:
            _PLAN_TIER_CACHE.popitem(last=False)
    return tier


def classify_plan_file(path: Path, frontmatter: dict[str, Any] | None = None) -> str:
    """Classify a canonical plan, falling back to tale for best-effort reads."""
    if frontmatter is None:
        frontmatter, _ = _read_plan_frontmatter(path)
    explicit = normalize_plan_tier(frontmatter.get("tier"))
    if explicit is not None:
        return explicit
    return "tale"
