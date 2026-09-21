"""Plan-path mapping for bead CLI handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.cli_location import (
    BeadsLocation,
    find_beads_location,
    resolve_beads_location,
)
from sase.bead.project import BEADS_DIRNAME

if TYPE_CHECKING:
    from sase.bead.operation_context import BeadOperationContext


def normalize_workspace_path(resolved: Path) -> Path:
    """Normalize a path from an ephemeral workspace to the primary workspace.

    If ``resolved`` is inside a sibling workspace (same parent directory as the
    primary workspace), rewrite it to be rooted at the primary workspace instead.
    This prevents ephemeral ``sase_<N>`` prefixes from leaking into stored paths.
    """
    from sase.bead.workspace import resolve_primary_workspace

    primary = resolve_primary_workspace()
    if not primary:
        return resolved

    try:
        resolved.relative_to(primary)
        return resolved  # already inside primary
    except ValueError:
        pass

    # Check if inside a sibling workspace (same parent directory)
    try:
        rel_to_parent = resolved.relative_to(primary.parent)
    except ValueError:
        return resolved  # not in a sibling workspace

    parts = rel_to_parent.parts
    if len(parts) > 1 and _same_owner_workspace(primary.parent / parts[0], primary):
        return primary / Path(*parts[1:])
    return resolved


def storage_plan_path(
    resolved: Path,
    *,
    bead_context: BeadOperationContext | None = None,
) -> str:
    """Return the plan path representation to persist on a bead.

    Plans below a known SDD or local-archive plans root use canonical
    ``plan:`` references. External paths keep the legacy relative/absolute
    fallback after workspace-prefix normalization.
    """
    if bead_context is not None:
        contextual = _storage_plan_path_for_context(resolved, bead_context)
        if contextual is not None:
            return contextual

    canonical = _canonical_storage_plan_path(resolved)
    if canonical is not None:
        return canonical

    normalized = normalize_workspace_path(resolved)

    for root in _storage_relative_roots():
        try:
            return str(normalized.relative_to(root))
        except ValueError:
            continue

    return str(normalized)


def _same_owner_workspace(candidate: Path, primary: Path) -> bool:
    if candidate == primary:
        return True
    marker = candidate / ".sase" / "checkout.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        marker_primary = payload.get("primary_workspace_dir")
        if marker_primary is not None:
            try:
                return Path(str(marker_primary)).expanduser().resolve() == primary
            except OSError:
                return False

    prefix = f"{primary.name}_"
    if candidate.parent == primary.parent and candidate.name.startswith(prefix):
        return candidate.name.removeprefix(prefix).isdigit()
    return False


def _storage_plan_path_for_context(
    resolved: Path,
    bead_context: BeadOperationContext,
) -> str | None:
    try:
        from sase.sdd.plan_refs import plan_ref_for_store

        store = bead_context.location.store
        if store is None:
            store = _store_for_location(bead_context.location)
        workspace_dir = bead_context.primary_workspace or bead_context.location.root
        return plan_ref_for_store(resolved, store, workspace_dir=workspace_dir)
    except (AttributeError, ImportError, RuntimeError, ValueError):
        return None


def _store_for_location(location: BeadsLocation) -> Any:
    from sase.sdd.store import SddStore

    if location.beads_dirname == BEADS_DIRNAME:
        return SddStore(
            storage="in_tree",
            sdd_dir=location.root / "sdd",
            repo_root=location.root,
        )
    storage: Any = location.storage or "local"
    return SddStore(
        storage=storage,
        sdd_dir=location.root,
        repo_root=location.root,
    )


def _canonical_storage_plan_path(resolved: Path) -> str | None:
    location = resolve_beads_location(require_existing=True)
    if location is None:
        return None

    try:
        from sase.core.paths import sase_subdir
        from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots
    except (AttributeError, ImportError):
        return None

    roots: list[Path] = []
    if location.store is not None:
        try:
            roots.append(location.store.kind_root("plans"))
        except ValueError:
            pass
    elif location.beads_dirname == BEADS_DIRNAME:
        roots.append(location.root / "sdd" / "plans")
    else:
        roots.append(location.root / "plans")
    roots.append(sase_subdir("plans"))

    try:
        return canonicalize_plan_reference_from_roots(
            resolved,
            roots=tuple(roots),
        )
    except (AttributeError, ImportError, RuntimeError, ValueError):
        return None


def _storage_relative_roots() -> list[Path]:
    """Trusted roots that can produce stable storage-relative plan paths."""
    from sase.bead.workspace import resolve_primary_workspace

    roots: list[Path] = []
    primary = resolve_primary_workspace()
    if primary:
        roots.append(primary.resolve())
        return roots

    root, _beads_dirname = find_beads_location()
    roots.append(root.resolve())

    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)

    return roots
