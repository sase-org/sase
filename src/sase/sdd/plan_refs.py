"""Store-derived references to archived SDD plans."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.store import SddStore


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


__all__ = ["plan_ref_for_store"]
