"""Plan location and reference helpers for direct approval."""

from __future__ import annotations

from pathlib import Path

from sase.main._plan_direct_approval_shared import plan_stem
from sase.main.plan_direct_approval_types import (
    DirectApprovalKind,
    DirectApprovalLocation,
)


def classify_location(source_path: Path, cwd: Path | None) -> DirectApprovalLocation:
    try:
        resolved = source_path.expanduser().resolve(strict=False)
    except Exception:
        return "scratch"
    try:
        from sase.core.paths import sase_home

        plans_root = sase_home().expanduser().resolve(strict=False) / "plans"
        resolved.relative_to(plans_root)
    except (ValueError, OSError):
        pass
    else:
        return "proposal"
    committed_ref = committed_plan_ref(source_path)
    if committed_ref is not None:
        return "committed"
    return "scratch"


def committed_plan_ref(source_path: Path) -> str | None:
    try:
        from sase.sdd.plan_refs import (
            canonicalize_plan_reference_from_roots,
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )
    except Exception:
        return None
    try:
        cwd = Path.cwd()
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(cwd)
        roots = resolve_plan_roots(workspace_dir, workspace_num)
        return canonicalize_plan_reference_from_roots(
            source_path.expanduser().resolve(strict=False), roots=roots
        )
    except Exception:
        return None


def authored_tier(source_path: Path) -> str | None:
    try:
        from sase.sdd.plan_tiers import read_plan_tier
    except Exception:
        return None
    try:
        return read_plan_tier(source_path)
    except Exception:
        return None


def validation_size(validation: object) -> str | None:
    size = getattr(getattr(validation, "plan", None), "size", None)
    return str(size).strip() or None if isinstance(size, str) else None


def predicted_plan_ref(
    source_path: Path, kind: DirectApprovalKind, location: DirectApprovalLocation
) -> str:
    if kind == "approve" and location == "committed":
        return committed_plan_ref(source_path) or str(
            source_path.expanduser().resolve(strict=False)
        )
    if kind == "approve":
        if location == "proposal":
            proposal_ref = _proposal_ref(source_path)
            if proposal_ref is not None:
                return proposal_ref
        return str(source_path.expanduser().resolve(strict=False))
    # tale/commit: canonical ref the archive will produce.
    return f"plan:{_archive_yyyymm()}/{plan_stem(source_path)}.md"


def _archive_yyyymm() -> str:
    try:
        from sase.sdd.files import get_yyyymm

        return get_yyyymm()
    except Exception:
        pass
    from datetime import UTC, datetime

    try:
        from sase.core.time import get_timezone

        return datetime.now(get_timezone()).strftime("%Y%m")
    except Exception:
        return datetime.now(UTC).strftime("%Y%m")


def _proposal_ref(source_path: Path) -> str | None:
    try:
        resolved = source_path.expanduser().resolve(strict=False)
        parts = resolved.parts
        if len(parts) >= 3 and len(parts[-2]) == 6 and parts[-2].isdigit():
            return f"plan:{parts[-2]}/{resolved.name}"
    except Exception:
        return None
    return None


__all__ = [
    "authored_tier",
    "classify_location",
    "committed_plan_ref",
    "predicted_plan_ref",
    "validation_size",
]
