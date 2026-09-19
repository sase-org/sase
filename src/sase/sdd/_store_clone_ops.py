"""Public orchestration for provider-owned SDD store clones.

Implementation lives in focused remote, primary, admission, and common helper
modules. This module retains the established import surface for callers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path

from sase._git_remote import is_http_git_remote
from sase.sdd._store_clone_common import handle_failed_sdd_clone
from sase.sdd._store_clone_primary import (
    clone_sdd_store_from_primary,
    fast_forward_workspace_clone_from_primary,
)
from sase.sdd._store_clone_remote import (
    clone_sdd_store_to_path,
    is_transient_remote_clone_failure as _is_transient_remote_clone_failure,
)
from sase.sdd._store_clone_transaction import (
    ClonePublicationError,
    CloneTransactionTimeout,
    clone_materialization_transaction,
    valid_published_sdd_clone,
    validate_staged_sdd_clone,
)
from sase.sdd._store_types import SddMaterializationError


def clone_sdd_store(
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference_repo: Path | None = None,
    strict: bool = False,
    deadline: float | None = None,
    allow_unborn_head: bool = False,
) -> bool:
    """Materialize and publish a remote SDD store clone."""

    workspace_sdd = workspace_sdd.expanduser()
    if is_http_git_remote(remote_url):
        return handle_failed_sdd_clone(
            workspace_sdd,
            f"refusing HTTP(S) SDD sidecar remote {remote_url!r}; "
            "materialization requires an SSH or local Git remote and Git was "
            "not invoked",
            strict=strict,
            cleanup_path=None,
        )
    try:
        with clone_materialization_transaction(
            workspace_sdd,
            deadline=deadline,
        ) as transaction:
            if os.path.lexists(workspace_sdd):
                if valid_published_sdd_clone(
                    workspace_sdd,
                    expected_remote=remote_url,
                    deadline=deadline,
                    allow_unborn_head=allow_unborn_head,
                ):
                    return True
                return handle_failed_sdd_clone(
                    workspace_sdd,
                    f"refusing to overwrite existing SDD store at {workspace_sdd}; "
                    "the concurrently materialized destination is not a healthy "
                    "clone of the configured remote",
                    strict=strict,
                    cleanup_path=transaction.clone_path,
                )
            cloned = clone_sdd_store_to_path(
                remote_url,
                transaction.clone_path,
                reference_repo=reference_repo,
                strict=strict,
                deadline=deadline,
                canonical_sdd=workspace_sdd,
            )
            if not cloned:
                return False
            try:
                transaction.publish(
                    expected_remote=remote_url,
                    deadline=deadline,
                    allow_unborn_head=allow_unborn_head,
                )
            except ClonePublicationError as exc:
                return handle_failed_sdd_clone(
                    workspace_sdd,
                    str(exc),
                    strict=strict,
                    cause=exc,
                    cleanup_path=transaction.clone_path,
                )
            return True
    except CloneTransactionTimeout as exc:
        return handle_failed_sdd_clone(
            workspace_sdd,
            str(exc),
            strict=strict,
            cause=exc,
            transient=True,
            cleanup_path=None,
        )


@contextmanager
def staged_sdd_clone_replacement(
    workspace_sdd: Path,
    primary_sdd: Path,
    remote_url: str | None,
    *,
    deadline: float | None = None,
    allow_unborn_head: bool = False,
) -> Iterator[Path]:
    """Yield a validated staged clone for replacing an existing workspace path."""

    expected_remote = remote_url or str(primary_sdd)
    with clone_materialization_transaction(
        workspace_sdd,
        deadline=deadline,
    ) as transaction:
        cloned = clone_sdd_store_from_primary(
            primary_sdd,
            transaction.clone_path,
            deadline=deadline,
            remote_url=remote_url,
            publish=False,
        )
        if not cloned and remote_url:
            cloned = clone_sdd_store_to_path(
                remote_url,
                transaction.clone_path,
                strict=False,
                deadline=deadline,
                canonical_sdd=workspace_sdd,
            )
        if not cloned:
            raise SddMaterializationError(
                f"could not create replacement SDD sidecar clone for {workspace_sdd}"
            )
        validate_staged_sdd_clone(
            transaction.clone_path,
            expected_remote=expected_remote,
            deadline=deadline,
            allow_unborn_head=allow_unborn_head,
        )
        yield transaction.clone_path
