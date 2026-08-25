"""Path discovery and display helpers for the plan inventory."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from sase.core.paths import iter_sharded_files, sase_home
from sase.main.plan_inventory_models import DisplayPathRoots

_PLAN_METADATA_CACHE_MAX_ENTRIES = 512
_PlanMetadataSignature = tuple[int, int]


@dataclass(frozen=True)
class _PlanPathMetadata:
    """Best-effort metadata read from one plan-file snapshot."""

    title: str | None
    tier: str


_PLAN_METADATA_CACHE: OrderedDict[
    Path, tuple[_PlanMetadataSignature, _PlanPathMetadata]
] = OrderedDict()
_PLAN_METADATA_CACHE_LOCK = RLock()


def display_path_roots() -> DisplayPathRoots:
    """Return resolved roots used to shorten paths for display."""
    return DisplayPathRoots(
        sase_root=sase_home().expanduser().resolve(strict=False),
        home=Path.home().expanduser().resolve(strict=False),
    )


def archived_plan_paths() -> tuple[Path, ...]:
    """Return all archived plan proposal paths."""
    return tuple(
        path for path in iter_sharded_files("plans", pattern="*.md") if path.is_file()
    )


def display_path(
    path: str | None,
    *,
    display_roots: DisplayPathRoots | None = None,
) -> str:
    """Shorten a path beneath the SASE or user home directory."""
    if not path:
        return "-"
    roots = display_roots or display_path_roots()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    try:
        return f"~/.sase/{resolved.relative_to(roots.sase_root)}"
    except ValueError:
        pass

    try:
        relative = resolved.relative_to(roots.home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative}"


def plan_metadata_for_path(path: str | None) -> _PlanPathMetadata:
    """Return normalized title and tier from one best-effort plan-file read.

    Reads are memoized against the plan file's ``(mtime_ns, size)`` signature,
    mirroring ``sase.sdd.plan_tiers``'s ``_PLAN_TIER_CACHE`` idea, so a plan
    file that has not changed since its last read does not pay a fresh read
    and YAML parse on every call.
    """
    unavailable = _PlanPathMetadata(title=None, tier="-")
    if not path:
        return unavailable

    candidate = Path(path).expanduser()
    try:
        stat = candidate.stat()
    except OSError:
        return unavailable
    signature: _PlanMetadataSignature = (stat.st_mtime_ns, stat.st_size)

    with _PLAN_METADATA_CACHE_LOCK:
        entry = _PLAN_METADATA_CACHE.get(candidate)
        if entry is not None and entry[0] == signature:
            _PLAN_METADATA_CACHE.move_to_end(candidate)
            return entry[1]

    metadata = _read_plan_metadata(candidate)
    with _PLAN_METADATA_CACHE_LOCK:
        _PLAN_METADATA_CACHE[candidate] = (signature, metadata)
        _PLAN_METADATA_CACHE.move_to_end(candidate)
        while len(_PLAN_METADATA_CACHE) > _PLAN_METADATA_CACHE_MAX_ENTRIES:
            _PLAN_METADATA_CACHE.popitem(last=False)
    return metadata


def _read_plan_metadata(path: Path) -> _PlanPathMetadata:
    unavailable = _PlanPathMetadata(title=None, tier="-")
    from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return unavailable

    frontmatter, error = parse_plan_frontmatter(content)
    if error is not None:
        return unavailable
    raw_title = frontmatter.get("title")
    title = " ".join(raw_title.split()) if isinstance(raw_title, str) else None
    return _PlanPathMetadata(
        title=title or None,
        tier=normalize_plan_tier(frontmatter.get("tier")) or "-",
    )


def normalize_plan_inventory_path(path: str | None) -> str | None:
    """Map a historical neutral-bundle resource to its durable proposal."""
    if not path:
        return path
    candidate = Path(path).expanduser()
    from sase.notification_gates.paths import interaction_requests_dir

    requests_root = interaction_requests_dir().expanduser().resolve(strict=False)
    try:
        candidate.resolve(strict=False).relative_to(requests_root)
    except ValueError:
        return path

    from sase.plan_gate import original_plan_file_for_resource

    original = original_plan_file_for_resource(candidate)
    return str(original) if original is not None else path
