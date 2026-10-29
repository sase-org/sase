"""Carry-repository evidence and current-obligation coverage helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from sase.core.finalizer_facade import check_repository_action
from sase.core.finalizer_wire import (
    FinalizerContextWire,
    FinalizerHandoffWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
    RepositoryActionCheckRequestWire,
)


CARRY_EVIDENCE_KIND = "carried_repo"
PREPARED_EVIDENCE_KIND = "prepared_repo"
_COVERAGE_KINDS = frozenset({CARRY_EVIDENCE_KIND, PREPARED_EVIDENCE_KIND})
_CARRY_DECISION_KEYS = frozenset({"repo_id", "action"})


def carry_repo_ids(decisions: Mapping[str, Mapping[str, Any]]) -> frozenset[str]:
    """Return repository ids whose accepted action is ``carry``."""

    return frozenset(
        repo_id
        for repo_id, decision in decisions.items()
        if isinstance(decision, Mapping) and decision.get("action") == "carry"
    )


def repos_with_action(
    repos: Sequence[Any],
    decisions: Mapping[str, Mapping[str, Any]],
    action: str,
    *,
    repo_id_of: Any,
) -> tuple[Any, ...]:
    """Filter *repos* to those whose accepted decision matches *action*."""

    return tuple(
        repo
        for repo in repos
        if decisions.get(repo_id_of(repo), {}).get("action") == action
    )


def _encode_carry_evidence(
    *,
    repo_id: str,
    digest: str,
    staged_ref: str,
    kind: str = CARRY_EVIDENCE_KIND,
) -> FinalizerOutcomeEvidenceWire:
    """Record one carried (or prepared) repository without a commit receipt."""

    return FinalizerOutcomeEvidenceWire(
        kind=kind,
        value=json.dumps(
            {
                "digest": digest,
                "repo_id": repo_id,
                "staged_ref": staged_ref,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def carry_evidence_for_context(
    decisions: Mapping[str, Mapping[str, Any]],
    context: FinalizerContextWire,
) -> list[FinalizerOutcomeEvidenceWire]:
    """Build carry evidence for every accepted carry decision in *context*."""

    return _coverage_evidence_for_ids(
        sorted(carry_repo_ids(decisions)),
        context,
        kind=CARRY_EVIDENCE_KIND,
    )


def prepared_evidence_for_ids(
    repo_ids: Sequence[str],
    context: FinalizerContextWire,
) -> list[FinalizerOutcomeEvidenceWire]:
    """Build prepared-coverage evidence for sealed repositories in *context*."""

    return _coverage_evidence_for_ids(
        repo_ids,
        context,
        kind=PREPARED_EVIDENCE_KIND,
    )


def _coverage_evidence_for_ids(
    repo_ids: Sequence[str],
    context: FinalizerContextWire,
    *,
    kind: str,
) -> list[FinalizerOutcomeEvidenceWire]:
    staged_ref = _staged_ref_from_context(context)
    digest_by_id = {
        obligation.obligation_id: obligation.digest or ""
        for obligation in context.obligations
        if obligation.kind == "repository"
    }
    return [
        _encode_carry_evidence(
            repo_id=repo_id,
            digest=digest_by_id.get(repo_id, ""),
            staged_ref=staged_ref,
            kind=kind,
        )
        for repo_id in sorted(repo_ids)
    ]


def _parse_coverage_entry(
    item: FinalizerOutcomeEvidenceWire | Mapping[str, Any],
) -> tuple[str, str, str] | None:
    """Return ``(repo_id, digest, staged_ref)`` from one coverage evidence item."""

    kind: str
    raw: object
    if isinstance(item, FinalizerOutcomeEvidenceWire):
        kind = item.kind
        raw = item.value
    elif isinstance(item, Mapping):
        kind = str(item.get("kind") or "")
        raw = item.get("value")
    else:
        return None
    if kind not in _COVERAGE_KINDS or not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    repo_id = payload.get("repo_id")
    digest = payload.get("digest")
    staged_ref = payload.get("staged_ref")
    if not isinstance(repo_id, str) or not repo_id:
        return None
    if not isinstance(digest, str) or not isinstance(staged_ref, str):
        return None
    return repo_id, digest, staged_ref


def _covered_digests_by_repo(
    evidence: Sequence[FinalizerOutcomeEvidenceWire | Mapping[str, Any]],
    staged_ref: str,
) -> dict[str, str]:
    """Map repository ids to the digest proven for the current staged identity."""

    covered: dict[str, str] = {}
    for item in evidence:
        parsed = _parse_coverage_entry(item)
        if parsed is None:
            continue
        repo_id, digest, evidence_staged = parsed
        if evidence_staged != staged_ref:
            continue
        covered[repo_id] = digest
    return covered


def current_commit_obligations_satisfied(
    payload: Mapping[str, Any],
    result: FinalizerInstanceResultWire,
) -> bool:
    """Return whether *result* proves every current repository obligation.

    Prior instance success is not enough: a later finalizer's new repository
    or a changed obligation digest must be observed again. Unchanged carried
    (or prepared) dirt with matching staged identity is a fixed point.
    """

    context = payload.get("context")
    if not isinstance(context, Mapping):
        return False
    raw_obligations = context.get("obligations")
    if not isinstance(raw_obligations, list):
        return True
    obligations = [
        item
        for item in raw_obligations
        if isinstance(item, Mapping) and item.get("kind") == "repository"
    ]
    if not obligations:
        return True
    handoff = context.get("handoff")
    staged_ref = ""
    if isinstance(handoff, Mapping):
        staged_ref = str(handoff.get("staged_ref") or "")
    covered = _covered_digests_by_repo(result.evidence, staged_ref)
    for item in obligations:
        repo_id = item.get("obligation_id")
        digest = item.get("digest")
        if not isinstance(repo_id, str) or not repo_id:
            return False
        if not isinstance(digest, str):
            digest = ""
        if covered.get(repo_id) != digest:
            return False
    return True


def proven_coverage_ids_from_result_payload(
    payload: Mapping[str, Any] | None,
    *,
    digest_by_id: Mapping[str, str],
    staged_ref: str,
) -> frozenset[str]:
    """Return obligation ids proven by aggregate result evidence."""

    if not isinstance(payload, Mapping):
        return frozenset()
    instances = payload.get("instances")
    if not isinstance(instances, list):
        return frozenset()
    evidence: list[Any] = []
    for instance in instances:
        if not isinstance(instance, Mapping):
            continue
        items = instance.get("evidence")
        if isinstance(items, list):
            evidence.extend(items)
    covered = _covered_digests_by_repo(evidence, staged_ref)
    return frozenset(
        repo_id
        for repo_id, digest in covered.items()
        if digest_by_id.get(repo_id) == digest
    )


def check_carry_action(context: FinalizerContextWire) -> None:
    """Raise ``ValueError`` when Rust rejects carry against *context*."""

    outcome = _carry_action_outcome(context.handoff)
    if outcome.status == "allowed":
        return
    message = outcome.message or "carry is not allowed for this host context"
    raise ValueError(message)


def carry_action_allowed_for_handoff(
    handoff: FinalizerHandoffWire | None,
) -> bool:
    """Return whether ordinary carry is legal for this staged handoff.

    Prepared intents have their own host-coverage bridge. Until that bridge
    proves sealed coverage, their descriptors must not relax the ordinary
    declaration requirement merely because they name an intent.
    """
    if handoff is None or handoff.prepared_intent_ref is not None:
        return False
    return _carry_action_outcome(handoff).status == "allowed"


def _carry_action_outcome(handoff: FinalizerHandoffWire | None) -> Any:
    return check_repository_action(
        RepositoryActionCheckRequestWire(action="carry", handoff=handoff)
    )


def _staged_ref_from_context(context: FinalizerContextWire) -> str:
    handoff = context.handoff
    if handoff is None:
        return ""
    return handoff.staged_ref


def carry_decision_allowed_keys() -> frozenset[str]:
    return _CARRY_DECISION_KEYS


__all__ = [
    "CARRY_EVIDENCE_KIND",
    "PREPARED_EVIDENCE_KIND",
    "carry_action_allowed_for_handoff",
    "carry_decision_allowed_keys",
    "carry_evidence_for_context",
    "carry_repo_ids",
    "check_carry_action",
    "current_commit_obligations_satisfied",
    "prepared_evidence_for_ids",
    "proven_coverage_ids_from_result_payload",
    "repos_with_action",
]
