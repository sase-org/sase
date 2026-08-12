"""Launch-only materialization for prompt document-reference sidecars."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
from typing import Any

from sase.artifact_ref_prompt_context import (
    PromptRefContext,
    refresh_prompt_ref_context,
)


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MaterializationFailure:
    """One failed attempt to materialize a sidecar for a prompt ref kind."""

    kind: str
    role: str
    remote_url: str
    detail: str


def materialize_missing_document_roots(
    kinds: Sequence[str],
    context: PromptRefContext,
) -> tuple[PromptRefContext, tuple[MaterializationFailure, ...]]:
    """Clone missing sidecar roots for the document kinds cited by one segment."""

    if context.workspace_dir is None or context.workspace_num is None:
        return context, ()

    workspace_dir = context.workspace_dir
    workspace_num = context.workspace_num
    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(workspace_dir, workspace_num)
    except Exception:
        log.debug(
            "Unable to resolve SDD store for prompt ref materialization in %r",
            workspace_dir,
            exc_info=True,
        )
        return context, ()

    role_by_kind = _document_role_by_ref_kind(workspace_dir, store)
    failures: list[MaterializationFailure] = []
    cloned = False
    for kind in dict.fromkeys(kinds):
        role = role_by_kind.get(kind)
        if role is None:
            continue
        try:
            root = store.kind_root(role)
        except Exception:
            log.debug(
                "Unable to resolve root for SDD sidecar role %r", role, exc_info=True
            )
            continue
        if root.is_dir():
            continue
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue

        print(
            f"Materializing '{role}' sidecar for @{kind} references...",
            file=sys.stderr,
        )
        try:
            from sase.sdd.store import SddMaterializationError, ensure_sdd_kind_clone

            ensure_sdd_kind_clone(workspace_dir, workspace_num, role, strict=True)
            cloned = True
        except SddMaterializationError as exc:
            failures.append(_failure(kind, role, remote_url, exc))
        except Exception as exc:  # noqa: BLE001 - user-facing prompt diagnostic.
            failures.append(_failure(kind, role, remote_url, exc))

    if cloned:
        return refresh_prompt_ref_context(context), tuple(failures)
    return context, tuple(failures)


def _document_role_by_ref_kind(workspace: Path, store: Any) -> dict[str, str]:
    from sase._linked_repo_config import resolution_config
    from sase.content_layout import resolve_project_config_read_path
    from sase.sdd.store import document_sidecar_roles
    from sase.sidecar_ref_config import effective_sidecar_ref_policies

    roles = document_sidecar_roles(
        store.split_sidecar_roles(),
        include_plans=True,
    )
    try:
        config: Mapping[str, Any] = resolution_config(str(workspace), None)
    except Exception:
        config = {}
    try:
        source_path = resolve_project_config_read_path(workspace)
    except Exception:
        source_path = None
    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=workspace,
        roles=roles,
        source_path=source_path,
    )
    return {
        policy.ref_kind: policy.role
        for policy in policies.values()
        if policy.is_document
    }


def _failure(
    kind: str,
    role: str,
    remote_url: str,
    exc: BaseException,
) -> MaterializationFailure:
    detail = str(exc) or type(exc).__name__
    return MaterializationFailure(
        kind=kind,
        role=role,
        remote_url=remote_url,
        detail=(
            f"hint: could not materialize '{role}' sidecar from {remote_url}: "
            f"{detail}. Run `sase repo path {role} --ensure` to retry."
        ),
    )


__all__ = ["MaterializationFailure", "materialize_missing_document_roots"]
