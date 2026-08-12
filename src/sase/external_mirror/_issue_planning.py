"""Plan external issue creations and upstream-state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.bead.model import Issue, Status
from sase.bug_links import normalize_external_ref
from sase.vcs_provider import IssueWire

from ._issue_models import CoveredBead, CreateCandidate, TransitionCandidate
from .filters import IssueFilters
from .state import iso_utc


def plan_transitions(
    *,
    current_refs: dict[str, IssueWire],
    covered: dict[str, CoveredBead],
    upstream_states: dict[str, str],
    display_name: str,
    current_time: datetime,
) -> list[TransitionCandidate]:
    transitions: list[TransitionCandidate] = []
    for ref in sorted(current_refs):
        issue = current_refs[ref]
        covered_bead = covered.get(ref)
        if covered_bead is None:
            continue
        previous_state = upstream_states.get(ref)
        if previous_state is None or previous_state == issue.state:
            continue
        transitions.append(
            TransitionCandidate(
                bead_id=covered_bead.bead.id,
                ref=ref,
                new_upstream_state=issue.state,
                action=transition_action(
                    mirrored=covered_bead.mirrored,
                    new_upstream_state=issue.state,
                ),
                observation=(
                    f"Upstream issue {display_name}#{issue.number} changed state: "
                    f"{previous_state} -> {issue.state} (observed "
                    f"{iso_utc(current_time)} by external_issue_mirror)."
                ),
            )
        )

    for ref in sorted(upstream_states):
        previous_state = upstream_states[ref]
        if ref in current_refs or previous_state == "absent":
            continue
        covered_bead = covered.get(ref)
        if covered_bead is None:
            continue
        issue_id = ref.rsplit("#", 1)[-1]
        transitions.append(
            TransitionCandidate(
                bead_id=covered_bead.bead.id,
                ref=ref,
                new_upstream_state="absent",
                action="none",
                observation=(
                    f"Upstream issue {display_name}#{issue_id} is no longer present "
                    "in the tracker listing (deleted or transferred), observed "
                    f"{iso_utc(current_time)} by external_issue_mirror."
                ),
            )
        )
    return transitions


def build_create_candidate(
    issue: IssueWire, *, ref: str, display_name: str
) -> CreateCandidate:
    display_ref = f"bug:{display_name}#{issue.number}"
    title = issue.title.strip() or f"Issue #{issue.number}"
    body = issue.body.strip()
    provenance = (
        f"---\nMirrored from {issue.url} by SASE's `external_issue_mirror` chop.\n"
        f"Upstream state when mirrored: {issue.state}."
    )
    description = f"{body}\n\n{provenance}" if body else provenance
    return CreateCandidate(
        ref=ref,
        display_ref=display_ref,
        title=title,
        description=description,
        sort_key=(issue.updated_at, issue_identity(issue)),
    )


def preview_transition_refs(
    candidates: list[TransitionCandidate],
    *,
    covered: dict[str, CoveredBead],
    blocked_ids: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    closed_refs: list[str] = []
    reopened_refs: list[str] = []
    for candidate in candidates:
        covered_bead = covered.get(candidate.ref)
        if covered_bead is None or covered_bead.bead.id != candidate.bead_id:
            continue
        if candidate.action == "close" and not blocked_reason(
            covered_bead.bead,
            action=candidate.action,
            blocked_ids=blocked_ids,
        ):
            closed_refs.append(candidate.ref)
        elif candidate.action == "reopen" and not blocked_reason(
            covered_bead.bead,
            action=candidate.action,
            blocked_ids=blocked_ids,
        ):
            reopened_refs.append(candidate.ref)
    return tuple(closed_refs), tuple(reopened_refs)


def transition_action(
    *,
    mirrored: bool,
    new_upstream_state: str,
) -> Literal["close", "reopen", "none"]:
    if not mirrored:
        return "none"
    if new_upstream_state == "closed":
        return "close"
    if new_upstream_state == "open":
        return "reopen"
    return "none"


def transition_note(
    candidate: TransitionCandidate,
    *,
    action: Literal["close", "reopen", "none"],
    reason: str,
    applied: bool,
) -> str:
    if candidate.new_upstream_state == "absent":
        return f"{candidate.observation} The external link is stale."
    if applied and action == "close":
        return f"{candidate.observation} Closed this mirrored bead to match."
    if applied and action == "reopen":
        return f"{candidate.observation} Reopened this mirrored bead to match."
    if reason:
        return (
            f"{candidate.observation} This bead's status is unchanged ({reason}); "
            "reconcile deliberately."
        )
    return (
        f"{candidate.observation} This bead's status is unchanged; "
        "reconcile deliberately."
    )


def unclosed_ancestor_ids(beads: list[Issue]) -> frozenset[str]:
    by_id = {bead.id: bead for bead in beads}
    blocked: set[str] = set()
    for bead in beads:
        if bead.status is Status.CLOSED:
            continue
        parent_id = bead.parent_id
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            blocked.add(parent_id)
            parent = by_id.get(parent_id)
            parent_id = parent.parent_id if parent is not None else None
    return frozenset(blocked)


def blocked_reason(
    bead: Issue,
    *,
    action: Literal["close", "reopen"],
    blocked_ids: frozenset[str],
) -> str:
    if action == "close":
        if bead.status is Status.CLOSED:
            return "the bead is already closed"
        if bead.status in {Status.CLAIMED, Status.IN_PROGRESS}:
            return "an agent is working this bead"
        if bead.id in blocked_ids:
            return "the bead has unclosed descendants"
        return ""
    if bead.status is Status.CLOSED:
        return ""
    return "the bead is already open"


def build_identity_index(beads: list[Issue], *, project: str) -> dict[str, CoveredBead]:
    index: dict[str, CoveredBead] = {}
    for bead in beads:
        normalized = normalize_external_ref(bead.external_ref, project=project)
        if normalized and normalized not in index:
            index[normalized] = CoveredBead(bead, mirrored=True)
    for bead in beads:
        for raw_ref in bead.refs:
            if not raw_ref.strip().casefold().startswith("bug:"):
                continue
            normalized = normalize_external_ref(raw_ref, project=project)
            if normalized and normalized not in index:
                index[normalized] = CoveredBead(bead, mirrored=False)
    return index


def unmirrored_count(issues: list[IssueWire], filters: IssueFilters) -> int:
    return sum(1 for issue in issues if not filters.matches(issue))


def issue_identity(issue: IssueWire) -> str:
    return issue.provider_id or str(issue.number)
