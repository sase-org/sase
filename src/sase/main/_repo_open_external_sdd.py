"""Provision a registered project's plans sidecar into an external checkout."""

from __future__ import annotations

from pathlib import Path
import sys

from sase._linked_repo_paths import sidecar_repo_clone_dir
from sase.sdd._store_git import git_remote_url, same_git_remote
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_records import (
    is_materialized_record,
    read_sdd_store_record,
    write_sdd_store_record,
)
from sase.sdd._store_types import SddMaterializationError, SddStoreRecord


def provision_external_plans_sidecar(
    *,
    canonical_name: str,
    dest_dir: str,
    project_source_dir: str,
) -> None:
    """Clone the source project's plans sidecar into *dest_dir* when recorded.

    Failures print one warning on stderr and leave the open successful. An
    existing matching clone is left untouched; the checkout-local store
    record is rewritten only when it differs from the source record.
    """

    try:
        _provision_external_plans_sidecar(
            dest_dir=dest_dir,
            project_source_dir=project_source_dir,
        )
    except Exception as exc:
        detail = str(exc) or type(exc).__name__
        print(
            "warning: failed to provision plans sidecar for "
            f"{canonical_name}: {detail}. Rerun "
            f"`sase repo open {canonical_name}` to retry.",
            file=sys.stderr,
        )


def _provision_external_plans_sidecar(
    *,
    dest_dir: str,
    project_source_dir: str,
) -> None:
    record = read_sdd_store_record(project_source_dir)
    if (
        not is_materialized_record(record)
        or record is None
        or not record.is_sidecar_storage
        or record.plans is None
    ):
        return

    clone_dir = Path(sidecar_repo_clone_dir(dest_dir, "plans"))
    remote_url = record.plans.remote_url
    if clone_dir.exists() or clone_dir.is_symlink():
        if not _is_matching_plans_clone(clone_dir, remote_url):
            raise SddMaterializationError(
                f"existing plans clone at {clone_dir} does not match {remote_url}"
            )
    else:
        reference_dir = Path(sidecar_repo_clone_dir(project_source_dir, "plans"))
        reference_repo = (
            reference_dir
            if _is_matching_plans_clone(reference_dir, remote_url)
            else None
        )
        ensure_sidecar_sdd_clone(
            clone_dir,
            remote_url,
            reference_repo=reference_repo,
            strict=True,
        )
        if not _is_matching_plans_clone(clone_dir, remote_url):
            raise SddMaterializationError(
                f"could not create matching plans clone at {clone_dir}"
            )

    _write_checkout_local_record(dest_dir, record)


def _write_checkout_local_record(dest_dir: str, record: SddStoreRecord) -> None:
    existing = read_sdd_store_record(dest_dir)
    if existing == record:
        return
    write_sdd_store_record(dest_dir, record)


def _is_matching_plans_clone(clone_dir: Path, remote_url: str) -> bool:
    if not clone_dir.is_dir() or not (clone_dir / ".git").exists():
        return False
    origin = git_remote_url(clone_dir)
    return origin is not None and same_git_remote(origin, remote_url)


__all__ = ["provision_external_plans_sidecar"]
