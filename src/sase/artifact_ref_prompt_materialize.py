"""Launch-only materialization for prompt document-reference sidecars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import sys

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
    """Clone missing sidecar roots for the path-bound document kinds cited by one segment.

    Pointer kinds never materialize a sidecar: their expansion does not
    depend on a local checkout.
    """

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

    expansion_by_kind = {
        expansion.kind: expansion
        for expansion in context.artifact_context.document_expansions
    }
    failures: list[MaterializationFailure] = []
    cloned = False
    for kind in dict.fromkeys(kinds):
        expansion = expansion_by_kind.get(kind)
        if expansion is None or expansion.is_pointer:
            continue
        role = expansion.role
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
