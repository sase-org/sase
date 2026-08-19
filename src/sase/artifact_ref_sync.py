"""Domain policy for the ``@<kind>::`` ref-sync gesture.

Pure Python, no Textual import, blocking. Callers must run this off the UI
thread; see :mod:`sase.ace.tui.widgets._artifact_ref_sync` for the widget
side that submits it as a tracked session-worker proc.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase._git_remote import parse_hosted_git_remote
from sase.artifact_ref_models import ArtifactRefContext
from sase.sdd.store import BEADS_SIDECAR_ROLE, ensure_sdd_kind_clone, resolve_sdd_store


ArtifactRefSyncMode = Literal["clone", "pull", "rescan"]


@dataclass(frozen=True, slots=True)
class ArtifactRefSyncPlan:
    """One resolved plan for refreshing a kind's backing sources."""

    kind: str
    mode: ArtifactRefSyncMode
    role: str | None
    label: str
    checkout: Path | None


@dataclass(frozen=True, slots=True)
class ArtifactRefSyncOutcome:
    """The result of executing one :class:`ArtifactRefSyncPlan`."""

    plan: ArtifactRefSyncPlan
    ok: bool
    detail: str = ""


def plan_artifact_ref_sync(
    context: ArtifactRefContext,
    kind: str,
    *,
    workspace_dir: Path,
    workspace_num: int,
) -> ArtifactRefSyncPlan:
    """Resolve what refreshing *kind*'s sources should do.

    ``mode`` is ``clone`` when the role's ``kind_root`` is not a directory,
    ``pull`` when it exists and a remote is recorded, else ``rescan``.
    """

    role: str | None
    if kind == "bead":
        role = BEADS_SIDECAR_ROLE
    else:
        expansion = context.document_expansion_for(kind)
        role = expansion.role if expansion is not None else None

    if role is None:
        return ArtifactRefSyncPlan(
            kind=kind, mode="rescan", role=None, label=kind, checkout=None
        )

    store = resolve_sdd_store(workspace_dir, workspace_num)
    try:
        checkout = store.kind_root(role)
    except Exception:
        return ArtifactRefSyncPlan(
            kind=kind, mode="rescan", role=role, label=role, checkout=None
        )

    remote_url = store.remote_url_for_kind(role)
    mode: ArtifactRefSyncMode
    if not checkout.is_dir():
        mode = "clone"
    elif remote_url is not None:
        mode = "pull"
    else:
        mode = "rescan"

    label = _label_for_remote(remote_url) or role or kind
    return ArtifactRefSyncPlan(
        kind=kind, mode=mode, role=role, label=label, checkout=checkout
    )


def run_artifact_ref_sync(
    plan: ArtifactRefSyncPlan,
    *,
    workspace_dir: Path,
    workspace_num: int,
) -> ArtifactRefSyncOutcome:
    """Execute *plan*, blocking. Callers must run this off the UI thread.

    A failed sync must degrade to stale rows, never to a crash: every
    exception is caught and shortened into ``detail``.
    """

    if plan.mode == "rescan" or plan.role is None:
        return ArtifactRefSyncOutcome(plan=plan, ok=True)

    try:
        ensure_sdd_kind_clone(
            workspace_dir,
            workspace_num,
            plan.role,
            strict=True,
            fresh=True,
        )
    except Exception as exc:  # noqa: BLE001 - degrade to stale rows, never crash
        return ArtifactRefSyncOutcome(plan=plan, ok=False, detail=_short_detail(exc))
    return ArtifactRefSyncOutcome(plan=plan, ok=True)


def _label_for_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    hosted = parse_hosted_git_remote(remote_url)
    if hosted is None:
        return None
    return hosted.repo.rsplit("/", 1)[-1]


def _short_detail(exc: BaseException, *, limit: int = 60) -> str:
    text = (str(exc).strip() or type(exc).__name__).splitlines()[0]
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


__all__ = [
    "ArtifactRefSyncMode",
    "ArtifactRefSyncOutcome",
    "ArtifactRefSyncPlan",
    "plan_artifact_ref_sync",
    "run_artifact_ref_sync",
]
