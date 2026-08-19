"""Workspace clone synchronization for provider-owned SDD stores."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import materialization_lock
from sase.sdd._store_link import ensure_workspace_sdd_clone as _ensure_sdd_clone
from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
from sase.sdd._store_resolution import resolve_sdd_store
from sase.sdd._store_types import (
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    SddStore,
)

PrimaryWorkspaceResolver = Callable[[str, int], str]
StoreResolver = Callable[[str | Path, int], SddStore]


def ensure_workspace_sdd_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    strict: bool = False,
    resolve_store: StoreResolver = resolve_sdd_store,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> None:
    """Ensure a workspace-local clone, optionally failing the setup transaction."""

    owner_anchor = _inherited_sdd_record_owner_anchor(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    )
    if owner_anchor is not None:
        ensure_workspace_sdd_clone(
            owner_anchor,
            workspace_num,
            strict=strict,
            resolve_store=resolve_store,
            primary_workspace_resolver=primary_workspace_resolver,
        )
        return

    store = resolve_store(workspace_dir, workspace_num)
    if store.is_sidecar_storage:
        ensure_sdd_kind_clone(
            workspace_dir,
            workspace_num,
            "plans",
            strict=strict,
            resolve_store=resolve_store,
            primary_workspace_resolver=primary_workspace_resolver,
        )
        return

    _ensure_sdd_clone(
        workspace_dir,
        workspace_num,
        resolve_store=resolve_store,
        primary_workspace_dir=primary_workspace_resolver,
        strict=strict,
    )


def ensure_sdd_kind_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    kind: str,
    *,
    strict: bool = False,
    fresh: bool = False,
    resolve_store: StoreResolver = resolve_sdd_store,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path:
    """Materialize and synchronize the sidecar clone backing *kind*.

    ``fresh`` forces a remote integration even within the configured TTL.
    """

    owner_anchor = _inherited_sdd_record_owner_anchor(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    )
    if owner_anchor is not None:
        return ensure_sdd_kind_clone(
            owner_anchor,
            workspace_num,
            kind,
            strict=strict,
            fresh=fresh,
            resolve_store=resolve_store,
            primary_workspace_resolver=primary_workspace_resolver,
        )

    store = resolve_store(workspace_dir, workspace_num)
    root = store.kind_root(kind)
    if not store.is_sidecar_storage:
        if store.storage == SDD_STORAGE_SEPARATE_REPO:
            ensure_workspace_sdd_clone(
                workspace_dir,
                workspace_num,
                strict=strict,
                resolve_store=resolve_store,
                primary_workspace_resolver=primary_workspace_resolver,
            )
        return root

    if kind == "beads" and store.beads_dir is not None:
        clone = ensure_beads_sidecar_clone(
            workspace_dir,
            workspace_num,
            fresh=fresh,
            primary_workspace_resolver=primary_workspace_resolver,
        )
        if clone is None and strict:
            raise SddMaterializationError(
                "no beads sidecar is recorded for this SDD store"
            )
        return root

    remote_url = store.remote_url_for_kind(kind)
    if remote_url is None:
        if strict:
            raise SddMaterializationError(f"no remote URL recorded for SDD kind {kind}")
        return root

    from sase.sdd._store_link import ensure_sidecar_sdd_clone

    ensure_sidecar_sdd_clone(
        root if kind != "beads" else root.parent,
        remote_url,
        strict=strict,
        fresh=fresh,
    )
    return root


def ensure_beads_sidecar_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    fresh: bool = False,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path | None:
    """Materialize the recorded beads sidecar for one workspace.

    Schema-2 stores deliberately keep bead state in the plans sidecar, so they
    return ``None`` without creating a ``sase/repos/beads`` clone. ``fresh``
    forces a remote integration even within the configured TTL.
    """

    owner_anchor = _inherited_sdd_record_owner_anchor(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    )
    if owner_anchor is not None:
        return ensure_beads_sidecar_clone(
            owner_anchor,
            workspace_num,
            fresh=fresh,
            primary_workspace_resolver=primary_workspace_resolver,
        )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        primary_workspace_resolver(str(workspace), workspace_num)
    ).expanduser()

    with materialization_lock(primary):
        record = read_sdd_store_record(primary)
        if (
            not is_materialized_record(record)
            or record is None
            or not record.is_sidecar_storage
            or record.beads is None
        ):
            return None

        from sase._linked_repo_paths import sidecar_repo_clone_dir
        from sase.sdd._store_link import ensure_sidecar_sdd_clone

        clone_dir = Path(sidecar_repo_clone_dir(workspace, "beads"))
        try:
            ensure_sidecar_sdd_clone(
                clone_dir,
                record.beads.remote_url,
                strict=True,
                fresh=fresh,
            )
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            raise SddMaterializationError(
                "could not materialize beads sidecar repository "
                f"{record.beads.repo} from {record.beads.remote_url} at "
                f"{clone_dir}: {detail}. Verify that the repository exists "
                "and your Git credentials can read it."
            ) from exc
        return clone_dir


def _inherited_sdd_record_owner_anchor(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path | None:
    """Return the owning checkout when a nested repo inherited its SDD record."""

    workspace = Path(workspace_dir).expanduser().resolve(strict=False)
    primary = Path(primary_workspace_resolver(str(workspace), workspace_num))
    record = read_sdd_store_record(primary)
    if not is_materialized_record(record):
        return None

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(workspace))
    except Exception:
        return None
    if found is None:
        return None

    checkout_dir, marker = found
    owner_anchor = Path(checkout_dir).expanduser().resolve(strict=False)
    if owner_anchor == workspace:
        return None

    marker_primary = (
        Path(marker.primary_workspace_dir).expanduser().resolve(strict=False)
    )
    if Path(primary).expanduser().resolve(strict=False) != marker_primary:
        return None
    return owner_anchor
