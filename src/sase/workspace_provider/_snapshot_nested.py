"""Strict nested-repository preservation before destructive removal."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.workspace_provider._snapshot_capture import snapshot_git_repo
from sase.workspace_provider._snapshot_model import (
    NestedPreservationError,
    PreservationError,
)


@dataclass(frozen=True)
class NestedPreservation:
    """Proof that nested checkouts were captured or proven empty of work."""

    locations: tuple[str, ...]
    roots: tuple[Path, ...]


def format_preservation_locations(locations: Sequence[str]) -> str:
    """Render captured snapshot locators for an operation diagnostic."""
    unique = tuple(dict.fromkeys(location for location in locations if location))
    if not unique:
        return ""
    return f"; recoverable work preserved at {', '.join(unique)}"


def preserve_nested_repositories(
    parent_root: str | Path,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
    reason: str,
    within: Sequence[str | Path] = (),
    already_proven: Sequence[str | Path] = (),
) -> NestedPreservation:
    """Snapshot every nested git checkout that a removal is about to destroy.

    Returns locators for captured dirty trees. A nested checkout whose
    snapshot returns ``None`` is a proven no-work tree. Enumeration or
    capture failure raises :class:`NestedPreservationError` and must not be
    treated as permission to delete. Locators captured before a later
    failure are attached to the error.
    """
    parent = Path(parent_root).expanduser()
    proven = {Path(path).expanduser().resolve(strict=False) for path in already_proven}
    roots = _discover_nested_git_repos(parent, within=within)
    locations: list[str] = []
    kept: list[Path] = []
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved in proven:
            continue
        kept.append(root)
        try:
            record = snapshot_git_repo(
                root,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                label=_label_for(root, parent),
                reason=reason,
            )
        except PreservationError as exc:
            raise NestedPreservationError(
                f"could not preserve nested repository {root}: {exc}",
                locations=locations,
                nested_root=root,
                dirty_paths=_dirty_paths_for(root),
            ) from exc
        except Exception as exc:
            raise NestedPreservationError(
                f"could not preserve nested repository {root}: {exc}",
                locations=locations,
                nested_root=root,
                dirty_paths=_dirty_paths_for(root),
            ) from exc
        if record is not None:
            locations.append(str(record.manifest_path.resolve(strict=False)))
    return NestedPreservation(locations=tuple(locations), roots=tuple(kept))


def _discover_nested_git_repos(
    parent_root: str | Path,
    *,
    within: Sequence[str | Path] = (),
) -> tuple[Path, ...]:
    """Find nested git checkouts under *parent_root* or *within*.

    A listing or inspectability failure raises :class:`PreservationError`
    rather than omitting an unreadable target. ``.git`` files (worktrees)
    count as well as ``.git`` directories.
    """
    parent = Path(parent_root).expanduser()
    parent_key = parent.resolve(strict=False)
    found: dict[Path, Path] = {}
    if within:
        search = [Path(path).expanduser() for path in within]
    else:
        repos = parent / "sase" / "repos"
        if not os.path.lexists(repos):
            return ()
        search = [repos]
    for start in search:
        _collect_git_roots(start, parent_key, found)
    return tuple(found[key] for key in sorted(found))


def _collect_git_roots(
    start: Path,
    parent_key: Path,
    found: dict[Path, Path],
) -> None:
    if not os.path.lexists(start):
        return
    try:
        if start.is_symlink():
            return
        start_key = start.resolve(strict=False)
        git_marker = start / ".git"
        # Path.exists() on 3.12/3.13 raises PermissionError when a parent
        # directory is unreadable; 3.14's os.path.exists returns False. Either
        # way an inspectability failure must become PreservationError rather
        # than omitting an unreadable nested checkout.
        if start.is_dir() and (git_marker.exists() or os.path.lexists(git_marker)):
            if start_key != parent_key:
                found[start_key] = start
                return
        if not start.is_dir():
            return
        children = sorted(start.iterdir(), key=lambda path: path.name)
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            _collect_git_roots(child, parent_key, found)
    except OSError as exc:
        raise PreservationError(
            f"cannot enumerate nested repositories under {start}: {exc}"
        ) from exc


def _dirty_paths_for(root: Path) -> tuple[str, ...]:
    from sase.workspace_provider.slot_refusal import bounded_dirty_paths

    listed = bounded_dirty_paths(root)
    return listed if listed is not None else ()


def _label_for(root: Path, parent: Path) -> str:
    try:
        rel = (
            root.resolve(strict=False)
            .relative_to(parent.resolve(strict=False))
            .as_posix()
        )
    except ValueError:
        return root.name or "nested"
    prefix = "sase/repos/"
    if rel.startswith(prefix):
        rest = rel[len(prefix) :]
        if rest.startswith("linked/"):
            return f"linked-{rest[len('linked/') :].replace('/', '-')}"
        if rest.startswith("external/"):
            return f"external-{rest[len('external/') :]}"
        return rest.split("/", 1)[0] or "sidecar"
    return rel.replace("/", "-") or "nested"
