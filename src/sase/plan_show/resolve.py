"""Resolve a ``sase plan show`` target through the five-rung ladder.

``auto`` mode tries the rungs below in order and the first definitive match
wins: ``path`` (an existing file), ``ref`` (a ``plans:`` reference or legacy
marker path, Rust-resolved), ``proposal`` (a pending-approval selector),
``name`` (a corpus slug lookup), and ``bead`` (a bead's stored ``design``
reference). ``-t/--target`` forces exactly one rung with no fallthrough.
Reference parsing/resolution and corpus discovery/ranking stay Rust-owned
through :mod:`sase.sdd.plan_refs` and :mod:`sase.plan_search.facade`; this
module only sequences those calls and never raises for user input.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import cast

from sase.bead.cli_common import get_read_view
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory_collectors import collect_proposed_plans
from sase.main.plan_inventory_paths import display_path_roots
from sase.main.plan_pending import resolve_pending_plan
from sase.notifications.models import Notification
from sase.notifications.pending_actions import PENDING_ACTION_PREFIX_LEN
from sase.plan_approval_actions import PlanApprovalActionError
from sase.plan_search import facade
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.sdd.plan_ref_display import describe_design_reference
from sase.sdd.plan_refs import (
    canonicalize_plan_reference_from_roots,
    resolve_plan_reference_from_roots,
    resolve_plan_roots,
    workspace_context_for_plan_resolution,
)

from .load import load_ambiguity_candidate, load_plan_show_record
from .model import (
    PlanShowAmbiguity,
    PlanShowMiss,
    PlanShowProposal,
    PlanShowRecord,
    PlanShowTarget,
    PlanShowTargetKind,
    PlanShowTargetStatus,
)

_PLAN_SEARCH_KINDS = frozenset({"tale", "epic", "local"})
_SUGGESTION_LIMIT = 5
_SUGGESTION_CUTOFF = 0.5
_RUNG_ORDER: tuple[PlanShowTargetKind, ...] = (
    "path",
    "ref",
    "proposal",
    "name",
    "bead",
)


@dataclass(frozen=True, slots=True)
class _Resolved:
    path: Path
    status: PlanShowTargetStatus
    candidates: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _Ambiguous:
    candidates: tuple[Path, ...]


_RungOutcome = _Resolved | _Ambiguous | None


@dataclass(frozen=True, slots=True)
class _Context:
    cwd: Path
    roots: tuple[Path, ...]
    repo_root: Path | str | None
    local_dir: Path | str | None
    corpus: tuple[PlanSearchMatch, ...] | None


def resolve_plan_show_target(
    raw: str | None,
    *,
    target_kind: str = "auto",
    cwd: Path | None = None,
    roots: tuple[Path, ...] | None = None,
    repo_root: Path | str | None = None,
    local_dir: Path | str | None = None,
    corpus: Sequence[PlanSearchMatch] | None = None,
) -> PlanShowRecord | PlanShowMiss | PlanShowAmbiguity:
    """Resolve *raw* to a plan record, a miss, or an ambiguity."""
    resolved_cwd = cwd or Path.cwd()
    resolved_roots = roots or _default_roots(resolved_cwd)
    context = _Context(
        cwd=resolved_cwd,
        roots=resolved_roots,
        repo_root=repo_root,
        local_dir=local_dir,
        corpus=tuple(corpus) if corpus is not None else None,
    )

    if raw is None:
        return _resolve_omitted_target(target_kind, context)

    if target_kind != "auto":
        outcome = _run_rung(cast(PlanShowTargetKind, target_kind), raw, context)
        return _finalize(raw, target_kind=target_kind, outcome=outcome, context=context)

    for kind in _RUNG_ORDER:
        outcome = _run_rung(kind, raw, context)
        if outcome is None:
            continue
        return _finalize(raw, target_kind=kind, outcome=outcome, context=context)
    return _final_miss(raw, context=context)


def _resolve_omitted_target(
    target_kind: str, context: _Context
) -> PlanShowRecord | PlanShowMiss:
    if target_kind not in ("auto", "proposal"):
        return PlanShowMiss(
            target="",
            reason=f"--target {target_kind} requires TARGET",
        )
    try:
        notification = resolve_pending_plan(None)
    except PlanApprovalActionError as exc:
        return PlanShowMiss(target="", reason=str(exc))
    plan_path = _notification_plan_path(notification)
    if plan_path is None:
        # The selector rung already degrades on this notification shape; the
        # omitted-TARGET path must too rather than assert its way out.
        return PlanShowMiss(
            target="",
            reason=(
                f"pending plan proposal {notification.id[:PENDING_ACTION_PREFIX_LEN]} "
                "records no plan file"
            ),
        )
    return load_plan_show_record(
        Path(plan_path),
        target=PlanShowTarget(raw=None, kind="proposal", status="exact"),
        roots=context.roots,
        proposal=_proposal_context(notification),
    )


def _run_rung(kind: PlanShowTargetKind, raw: str, context: _Context) -> _RungOutcome:
    if kind == "path":
        return _rung_path(raw, context)
    if kind == "ref":
        return _rung_ref(raw, context)
    if kind == "proposal":
        return _rung_proposal(raw, context)
    if kind == "name":
        return _rung_name(raw, context)
    return _rung_bead(raw, context)


def _finalize(
    raw: str,
    *,
    target_kind: str,
    outcome: _RungOutcome,
    context: _Context,
) -> PlanShowRecord | PlanShowMiss | PlanShowAmbiguity:
    if outcome is None:
        return _final_miss(raw, context=context)
    if isinstance(outcome, _Ambiguous):
        return PlanShowAmbiguity(
            target=raw,
            candidates=tuple(
                load_ambiguity_candidate(path, roots=context.roots)
                for path in outcome.candidates
            ),
        )
    kind = cast(PlanShowTargetKind, target_kind)
    proposal = (
        _proposal_context(resolve_pending_plan(raw)) if kind == "proposal" else None
    )
    bead = raw if kind == "bead" else None
    return load_plan_show_record(
        outcome.path,
        target=PlanShowTarget(
            raw=raw,
            kind=kind,
            status=outcome.status,
            candidates=tuple(str(path) for path in outcome.candidates),
        ),
        roots=context.roots,
        proposal=proposal,
        bead=bead,
    )


# --- rungs -----------------------------------------------------------------


def _rung_path(raw: str, context: _Context) -> _RungOutcome:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = context.cwd / candidate
    if not candidate.is_file():
        return None
    return _Resolved(candidate, "exact", (candidate,))


def _rung_ref(raw: str, context: _Context) -> _RungOutcome:
    resolution = resolve_plan_reference_from_roots(raw, roots=context.roots)
    if resolution.status in ("exact", "drifted"):
        assert resolution.resolved_path is not None
        return _Resolved(
            resolution.resolved_path,
            cast(PlanShowTargetStatus, resolution.status),
            resolution.candidates,
        )
    if resolution.status == "ambiguous":
        return _Ambiguous(resolution.candidates)
    return None


def _rung_proposal(raw: str, context: _Context) -> _RungOutcome:
    if _is_path_shaped(raw):
        return None
    try:
        notification = resolve_pending_plan(raw)
    except PlanApprovalActionError as exc:
        if exc.code == "ambiguous_prefix":
            matches = _matching_pending_notifications(raw)
            paths = tuple(
                Path(plan_path)
                for notification in matches
                if (plan_path := _notification_plan_path(notification)) is not None
            )
            if paths:
                return _Ambiguous(paths)
        return None
    plan_path = _notification_plan_path(notification)
    if plan_path is None:
        return None
    return _Resolved(Path(plan_path), "exact", (Path(plan_path),))


def _rung_name(raw: str, context: _Context) -> _RungOutcome:
    normalized = _normalize_name(raw)
    if not normalized:
        return None
    lowered = normalized.lower()
    matches: list[Path] = []
    for match in _discovered_plans(context):
        plan = match.plan
        if plan.kind not in _PLAN_SEARCH_KINDS:
            continue
        if lowered in {plan.name.lower(), _corpus_relative(plan).lower()}:
            matches.append(Path(plan.path))
    unique = tuple(dict.fromkeys(matches))
    if not unique:
        return None
    if len(unique) == 1:
        return _Resolved(unique[0], "exact", unique)
    return _Ambiguous(unique)


def _rung_bead(raw: str, context: _Context) -> _RungOutcome:
    if _is_path_shaped(raw):
        return None
    try:
        with get_read_view() as view:
            issue = view.show(raw)
    except (KeyError, ValueError):
        return None
    design = issue.design.strip()
    if not design:
        return None
    display = describe_design_reference(design, roots=context.roots, cwd=context.cwd)
    if not display.resolved:
        return None
    assert display.resolved_path is not None
    path = Path(display.resolved_path)
    status = cast(PlanShowTargetStatus, display.status)
    return _Resolved(path, status, (path,))


# --- helpers -----------------------------------------------------------------


def _default_roots(cwd: Path) -> tuple[Path, ...]:
    workspace_dir, workspace_num = workspace_context_for_plan_resolution(cwd)
    return resolve_plan_roots(workspace_dir, workspace_num)


def _is_path_shaped(raw: str) -> bool:
    return "/" in raw or raw.endswith(".md")


def _normalize_name(raw: str) -> str:
    normalized = raw.strip().removeprefix("plans:").removeprefix("./")
    return normalized.removesuffix(".md")


def _corpus_relative(plan: Plan) -> str:
    rel = plan.relpath.removesuffix(".md")
    if plan.source == facade.SOURCE_REPO and "/" in rel:
        rel = rel.split("/", 1)[1]
    return rel


def _discovered_plans(context: _Context) -> tuple[PlanSearchMatch, ...]:
    if context.corpus is not None:
        return context.corpus
    matches = facade.search(
        None,
        limit=0,
        repo_root=context.repo_root,
        local_dir=context.local_dir,
        cwd=context.cwd,
    )
    return tuple(match for match in matches if match.plan.kind in _PLAN_SEARCH_KINDS)


def _matching_pending_notifications(prefix: str) -> tuple[Notification, ...]:
    return tuple(
        notification
        for notification in visible_pending_plan_notifications()
        if notification.id == prefix or notification.id.startswith(prefix)
    )


def _notification_plan_path(notification: Notification) -> str | None:
    action_data = notification.action_data
    candidates = (
        action_data.get("original_plan_file"),
        *notification.files,
        action_data.get("plan_file"),
    )
    return next((value for value in candidates if value), None)


def _proposal_context(notification: Notification) -> PlanShowProposal | None:
    # Visibility is re-derived from live agents on every read, so the proposal
    # row can be gone by the time it is looked up. The plan itself still
    # resolved; drop the approval context rather than raise ``StopIteration``.
    proposed = next(
        (
            row
            for row in collect_proposed_plans(display_roots=display_path_roots())
            if row.notification_id == notification.id
        ),
        None,
    )
    if proposed is None:
        return None
    return PlanShowProposal(
        id=proposed.notification_id,
        id_prefix=proposed.id_prefix,
        agent=proposed.agent,
        project=proposed.project,
        provider_model=proposed.provider_model,
        age=proposed.age,
        response_dir=proposed.response_dir,
    )


def _final_miss(raw: str, *, context: _Context) -> PlanShowMiss:
    references = sorted(
        {
            canonicalize_plan_reference_from_roots(
                Path(match.plan.path), roots=context.roots
            )
            or match.plan.name
            for match in _discovered_plans(context)
        }
    )
    suggestions = list(
        get_close_matches(
            raw, references, n=_SUGGESTION_LIMIT, cutoff=_SUGGESTION_CUTOFF
        )
    )
    if not _is_path_shaped(raw):
        suggestions.extend(
            notification.id[:PENDING_ACTION_PREFIX_LEN]
            for notification in visible_pending_plan_notifications()
        )
    return PlanShowMiss(target=raw, suggestions=tuple(suggestions))


__all__ = ["resolve_plan_show_target"]
