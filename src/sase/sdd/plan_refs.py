"""Canonical parsing and resolution for archived SDD plan references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from sase.core.paths import sase_subdir
from sase.core.rust import require_rust_binding
from sase.sdd.store import SddStore, resolve_sdd_store


PLAN_REFERENCE_RESOLUTION_WIRE_SCHEMA_VERSION = 1
PlanReferenceResolutionStatus = Literal[
    "exact",
    "drifted",
    "ambiguous",
    "missing",
]


@dataclass(frozen=True)
class ParsedPlanReference:
    """A typed logical plan reference or an accepted legacy path."""

    kind: str
    path: str
    legacy: bool
    rendered: str


@dataclass(frozen=True)
class PlanReferenceResolution:
    """Structured result returned by the shared Rust resolver."""

    schema_version: int
    status: PlanReferenceResolutionStatus
    resolved_path: Path | None
    candidates: tuple[Path, ...]

    @property
    def best_path(self) -> Path | None:
        """Return the resolved path or first ordered candidate on a miss."""

        if self.resolved_path is not None:
            return self.resolved_path
        return self.candidates[0] if self.candidates else None


def resolve_plan_roots(
    workspace_dir: str | Path,
    workspace_num: int,
) -> tuple[Path, ...]:
    """Return the active store and machine-local plan roots in search order."""

    store = resolve_sdd_store(workspace_dir, workspace_num)
    roots = (
        store.kind_root("plans"),
        sase_subdir("plans"),
    )
    resolved: list[Path] = []
    for root in roots:
        normalized = root.expanduser().resolve(strict=False)
        if normalized not in resolved:
            resolved.append(normalized)
    return tuple(resolved)


def parse_plan_reference(value: str) -> ParsedPlanReference:
    """Parse *value* through the shared reference grammar."""

    binding = require_rust_binding("plan_reference_parse")
    raw = cast(dict[str, Any], binding(value))
    return ParsedPlanReference(
        kind=str(raw["kind"]),
        path=str(raw["path"]),
        legacy=bool(raw["legacy"]),
        rendered=str(raw["rendered"]),
    )


def render_plan_reference(path: str, *, kind: str = "plans") -> str:
    """Validate and render a typed logical plan reference."""

    binding = require_rust_binding("plan_reference_render")
    return str(binding(kind, path))


def canonicalize_plan_reference(
    plan_path: str | Path,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
) -> str | None:
    """Return a canonical reference when *plan_path* lies below a plan root."""

    path = Path(plan_path).expanduser().resolve(strict=False)
    roots = resolve_plan_roots(workspace_dir, workspace_num)
    binding = require_rust_binding("plan_reference_canonicalize")
    result = binding(str(path), [str(root) for root in roots])
    return None if result is None else str(result)


def resolve_plan_reference(
    value: str,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
) -> PlanReferenceResolution:
    """Resolve a logical reference or legacy path against active plan roots."""

    roots = resolve_plan_roots(workspace_dir, workspace_num)
    version_binding = require_rust_binding(
        "plan_reference_resolution_wire_schema_version"
    )
    binding_version = int(version_binding())
    if binding_version != PLAN_REFERENCE_RESOLUTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs plan-reference resolution wire is stale: "
            f"expected {PLAN_REFERENCE_RESOLUTION_WIRE_SCHEMA_VERSION}, "
            f"got {binding_version}"
        )

    binding = require_rust_binding("plan_reference_resolve")
    raw = cast(
        dict[str, Any],
        binding(value, [str(root) for root in roots]),
    )
    schema_version = int(raw["schema_version"])
    if schema_version != PLAN_REFERENCE_RESOLUTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an unsupported plan-reference resolution "
            f"wire: {schema_version}"
        )
    status = str(raw["status"])
    if status not in {"exact", "drifted", "ambiguous", "missing"}:
        raise RuntimeError(
            f"sase_core_rs returned an unknown plan-reference status: {status}"
        )
    raw_resolved_path = raw.get("resolved_path")
    return PlanReferenceResolution(
        schema_version=schema_version,
        status=cast(PlanReferenceResolutionStatus, status),
        resolved_path=(
            None if raw_resolved_path is None else Path(str(raw_resolved_path))
        ),
        candidates=tuple(Path(str(path)) for path in raw["candidates"]),
    )


def plan_ref_for_store(
    plan_path: Path,
    store: SddStore,
    *,
    workspace_dir: Path,
) -> str:
    """Return the stable plan reference persisted on a bead.

    In-tree and sidecar plans prefer workspace-relative paths. Local and
    separate-repository stores use the conventional ``.sase/sdd`` reference
    when the plan belongs to the resolved store.
    """
    plan_path = plan_path.expanduser().resolve(strict=False)
    workspace_dir = workspace_dir.expanduser().resolve(strict=False)

    if store.is_sidecar_storage:
        return _relative_or_absolute(plan_path, workspace_dir)

    if store.is_in_tree:
        return _relative_or_absolute(plan_path, workspace_dir)

    try:
        relative = plan_path.relative_to(
            store.sdd_dir.expanduser().resolve(strict=False)
        )
    except ValueError:
        return _relative_or_absolute(plan_path, workspace_dir)
    return (Path(".sase") / "sdd" / relative).as_posix()


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "PLAN_REFERENCE_RESOLUTION_WIRE_SCHEMA_VERSION",
    "ParsedPlanReference",
    "PlanReferenceResolution",
    "PlanReferenceResolutionStatus",
    "canonicalize_plan_reference",
    "parse_plan_reference",
    "plan_ref_for_store",
    "render_plan_reference",
    "resolve_plan_reference",
    "resolve_plan_roots",
]
