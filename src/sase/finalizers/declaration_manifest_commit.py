"""Commit-payload validation, deferrals, and manifest template helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.finalizer_facade import (
    validate_finalizer_bead_decision,
)
from sase.core.finalizer_wire import (
    FINALIZER_DEFERRAL_REASONS,
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerAssignedBeadWire,
    FinalizerContextWire,
    FinalizerDeferralWire,
    FinalizerPlanWire,
    finalizer_assigned_bead_from_dict,
    finalizer_deferral_from_dict,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.commit_carry import (
    carry_decision_allowed_keys,
    check_carry_action,
)
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    HostRepositoryRecord,
)
from sase.workflows.commit.message_validation import (
    check_commit_message,
    load_commit_message_policy,
)

PLACEHOLDER_COMMIT_MESSAGE = "feat(scope): describe the completed work"


@dataclass(frozen=True)
class CommitDeferralDecision:
    """One typed commit deferral submitted for host adjudication."""

    repo_id: str
    deferral: FinalizerDeferralWire


def manifest_template(context: FinalizerContextWire) -> dict[str, Any]:
    payloads: list[dict[str, Any]] = []
    repo_ids = [
        obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    ]
    for requirement in context.requirements:
        if (
            not requirement.submission_required
            and requirement.trigger != "dirty_repository"
        ):
            continue
        payload: Any
        if requirement.trigger == "dirty_repository":
            payload = {
                "repositories": [
                    {
                        "repo_id": repo_id,
                        "action": "commit",
                        "message": PLACEHOLDER_COMMIT_MESSAGE,
                        **(
                            {"bead_action": None}
                            if _context_assigned_bead(context) is not None
                            else {}
                        ),
                    }
                    for repo_id in repo_ids
                ],
                "deferrals": [],
            }
        else:
            payload = {}
        payloads.append({"instance_id": requirement.instance_id, "payload": payload})
    return {
        "schema_version": FINALIZER_WIRE_SCHEMA_VERSION,
        "run_id": context.run_id,
        "agent_id": context.agent_id,
        "turn_nonce": context.turn_nonce,
        "plan_digest": context.plan_digest,
        "context_digest": context.context_digest,
        "payloads": payloads,
    }


def validate_provider_payloads(
    plan: FinalizerPlanWire,
    context: FinalizerContextWire,
    envelope: Mapping[str, Any],
    *,
    host_records: Sequence[HostRepositoryRecord],
) -> None:
    entries = {entry.instance_id: entry for entry in plan.entries}
    payloads = envelope.get("payloads", [])
    if not isinstance(payloads, list):
        raise FinalizerDeclarationError(
            "final declaration submission payloads must be a list",
            code="submission_payloads_not_list",
        )
    for item in payloads:
        if not isinstance(item, Mapping):
            continue
        instance_id = item.get("instance_id")
        payload = item.get("payload")
        if not isinstance(instance_id, str):
            raise FinalizerDeclarationError(
                "final declaration payload instance_id must be a string",
                code="submission_instance_id_invalid",
            )
        entry = entries.get(instance_id)
        if entry is None:
            raise FinalizerDeclarationError(
                f"unknown finalizer instance {instance_id!r}",
                code="unknown_instance",
            )
        if entry.provider_ref == "builtin@commit":
            _validate_commit_payload(context, payload, host_records=host_records)
        elif entry.provider_ref != "builtin@command":
            from sase.finalizers.executor import (
                FinalizerExecutionError,
                validate_external_declaration_payload,
            )

            try:
                validate_external_declaration_payload(
                    instance_id,
                    entry.provider_ref,
                    context,
                    payload,
                    selected=tuple(item.instance_id for item in plan.entries),
                )
            except FinalizerExecutionError as exc:
                raise FinalizerDeclarationError(
                    str(exc),
                    code="external_payload_invalid",
                ) from exc


def _validate_commit_payload(
    context: FinalizerContextWire,
    payload: Any,
    *,
    host_records: Sequence[HostRepositoryRecord],
) -> None:
    if not isinstance(payload, Mapping):
        raise FinalizerDeclarationError(
            "commit finalizer payload must be an object",
            code="commit_payload_not_object",
        )
    raw_repositories = payload.get("repositories")
    if not isinstance(raw_repositories, list):
        raise FinalizerDeclarationError(
            "commit finalizer payload requires repositories list",
            code="commit_repositories_missing",
        )
    expected = _repository_obligation_paths(context)
    seen: set[str] = set()
    for index, decision in enumerate(raw_repositories):
        if not isinstance(decision, Mapping):
            raise FinalizerDeclarationError(
                f"commit repository decision #{index + 1} must be an object",
                code="commit_decision_not_object",
            )
        repo_id = decision.get("repo_id")
        if not isinstance(repo_id, str) or not repo_id:
            raise FinalizerDeclarationError(
                f"commit repository decision #{index + 1} requires repo_id",
                code="commit_repo_id_missing",
            )
        if repo_id not in expected:
            raise FinalizerDeclarationError(
                f"commit repository decision names unknown repo_id {repo_id!r}",
                code="commit_repo_id_unknown",
            )
        if repo_id in seen:
            raise FinalizerDeclarationError(
                f"commit repository decision duplicates repo_id {repo_id!r}",
                code="commit_repo_id_duplicate",
            )
        seen.add(repo_id)
        action = decision.get("action")
        if action == "commit":
            _validate_commit_decision(
                context, repo_id, decision, host_records=host_records
            )
        elif action == "carry":
            _validate_carry_decision(context, repo_id, decision)
        else:
            raise FinalizerDeclarationError(
                f"commit repository decision for {repo_id} has invalid action; "
                "legal actions are 'commit' and, when the host context allows "
                "it, 'carry'",
                code="commit_action_invalid",
            )
    missing = set(expected) - seen
    if missing:
        raise FinalizerDeclarationError(
            "commit finalizer payload is missing repository decision(s): "
            + ", ".join(sorted(missing)),
            code="commit_repo_decision_missing",
        )
    deferrals = commit_deferral_decisions_for_payload(context, payload)
    carried = {
        str(decision.get("repo_id"))
        for decision in raw_repositories
        if isinstance(decision, Mapping) and decision.get("action") == "carry"
    }
    for item in deferrals:
        if item.repo_id in carried:
            raise FinalizerDeclarationError(
                f"repository {item.repo_id} cannot be carried and deferred",
                code="commit_carry_deferral_conflict",
            )


def commit_deferral_decisions_for_payload(
    context: FinalizerContextWire,
    payload: Mapping[str, Any],
) -> tuple[CommitDeferralDecision, ...]:
    """Return structurally valid typed commit deferrals from *payload*."""

    expected = _repository_obligation_paths(context)
    raw_deferrals = payload.get("deferrals", [])
    if not isinstance(raw_deferrals, list):
        raise FinalizerDeclarationError(
            "commit finalizer payload deferrals must be a list",
            code="commit_deferrals_not_list",
        )

    decisions: list[CommitDeferralDecision] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_decision in enumerate(raw_deferrals):
        if not isinstance(raw_decision, Mapping):
            raise FinalizerDeclarationError(
                f"commit deferral #{index + 1} must be an object",
                code="commit_deferral_not_object",
            )
        decision = dict(raw_decision)
        _reject_extra_keys(decision, {"repo_id", "reason", "paths"}, "defer")
        repo_id = decision.get("repo_id")
        if not isinstance(repo_id, str) or not repo_id:
            raise FinalizerDeclarationError(
                f"commit deferral #{index + 1} requires repo_id",
                code="commit_deferral_repo_id_missing",
            )
        if repo_id not in expected:
            raise FinalizerDeclarationError(
                f"commit deferral names unknown repo_id {repo_id!r}",
                code="commit_deferral_repo_id_unknown",
            )
        reason = decision.get("reason")
        if reason not in FINALIZER_DEFERRAL_REASONS:
            allowed = ", ".join(FINALIZER_DEFERRAL_REASONS)
            raise FinalizerDeclarationError(
                f"commit deferral for {repo_id} has invalid reason {reason!r}; "
                f"expected one of: {allowed}",
                code="commit_deferral_reason_invalid",
            )
        raw_paths = decision.get("paths")
        if not (
            isinstance(raw_paths, list)
            and raw_paths
            and all(isinstance(path, str) and path for path in raw_paths)
        ):
            raise FinalizerDeclarationError(
                f"commit deferral for {repo_id} requires nonblank paths",
                code="commit_deferral_paths_missing",
            )
        if len(set(raw_paths)) != len(raw_paths):
            raise FinalizerDeclarationError(
                f"commit deferral for {repo_id} contains duplicate paths",
                code="commit_deferral_path_duplicate",
            )
        unknown_paths = sorted(set(raw_paths) - set(expected[repo_id]))
        if unknown_paths:
            raise FinalizerDeclarationError(
                f"commit deferral for {repo_id} names path(s) outside the "
                "repository obligation: " + ", ".join(unknown_paths),
                code="commit_deferral_path_unknown",
            )
        key = (repo_id, str(reason))
        if key in seen:
            raise FinalizerDeclarationError(
                f"commit deferral duplicates {reason!r} for {repo_id}",
                code="commit_deferral_duplicate",
            )
        seen.add(key)
        decisions.append(
            CommitDeferralDecision(
                repo_id=repo_id,
                deferral=finalizer_deferral_from_dict(decision),
            )
        )
    return tuple(decisions)


_COMMIT_DECISION_KEYS = {
    "repo_id",
    "action",
    "message",
    "bead_action",
    "bead_id",
    "bead_status",
    "repository_scope",
    "commit_method",
    "legacy_do_not_close_bead",
}
_BEAD_DECISION_KEYS = {
    "repo_id",
    "commit_method",
    "bead_action",
    "bead_id",
    "bead_status",
    "repository_scope",
    "legacy_do_not_close_bead",
}


def _assigned_bead_status(bead_id: str, cwd: str) -> str:
    from sase.workflows.commit.bead_hooks import bead_status_fact

    return bead_status_fact(bead_id, cwd)


def _host_close_bead_status(
    bead_id: str,
    primary_repo_obligation_id: str | None,
    host_records: Sequence[HostRepositoryRecord],
) -> str:
    path: str | None = None
    for record in host_records:
        if record.obligation_id == primary_repo_obligation_id:
            path = record.path
            break
    if not path:
        return "unreadable"
    try:
        return _assigned_bead_status(bead_id, path)
    except Exception:
        return "unreadable"


def _is_placeholder_commit_message(message: str) -> bool:
    """Return whether ``message`` is the manifest template's placeholder."""

    return " ".join(message.split()) == PLACEHOLDER_COMMIT_MESSAGE


def reject_placeholder_commit_messages(declaration: Mapping[str, Any]) -> None:
    """Raise if any commit decision in ``declaration`` keeps the template message."""

    payloads = declaration.get("payloads")
    if not isinstance(payloads, list):
        return
    for entry in payloads:
        payload = entry.get("payload") if isinstance(entry, Mapping) else None
        repositories = (
            payload.get("repositories") if isinstance(payload, Mapping) else None
        )
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            if not isinstance(decision, Mapping):
                continue
            message = decision.get("message")
            if isinstance(message, str) and _is_placeholder_commit_message(message):
                raise FinalizerDeclarationError(
                    f"commit decision for {decision.get('repo_id')} still has the "
                    "manifest template's placeholder message; describe the work "
                    "done in that repository",
                    code="commit_message_placeholder",
                )


def _validate_carry_decision(
    context: FinalizerContextWire,
    repo_id: str,
    decision: Mapping[str, Any],
) -> None:
    _reject_extra_keys(decision, set(carry_decision_allowed_keys()), "carry")
    try:
        check_carry_action(context)
    except ValueError as exc:
        raise FinalizerDeclarationError(
            f"carry decision for {repo_id} is not allowed: {exc}",
            code="commit_action_invalid",
        ) from exc


def _validate_commit_decision(
    context: FinalizerContextWire,
    repo_id: str,
    decision: Mapping[str, Any],
    *,
    host_records: Sequence[HostRepositoryRecord],
) -> None:
    _reject_extra_keys(decision, _COMMIT_DECISION_KEYS, "commit")
    message = decision.get("message")
    if not isinstance(message, str) or not message.strip():
        raise FinalizerDeclarationError(
            f"commit decision for {repo_id} requires a nonblank message",
            code="commit_message_missing",
        )
    if len(message) > 4000:
        raise FinalizerDeclarationError(
            f"commit decision for {repo_id} has an oversized message",
            code="commit_message_too_large",
        )
    if _is_placeholder_commit_message(message):
        raise FinalizerDeclarationError(
            f"commit decision for {repo_id} still has the manifest template's "
            "placeholder message; describe the work done in that repository",
            code="commit_message_placeholder",
        )
    rejection = check_commit_message(message, load_commit_message_policy())
    if rejection is not None:
        raise FinalizerDeclarationError(
            f"commit decision for {repo_id} has a non-conventional message",
            code="commit_message_invalid",
        )
    assigned = _context_assigned_bead(context)
    has_bead_fields = any(
        key in decision for key in _BEAD_DECISION_KEYS if key != "repo_id"
    )
    if assigned is None and not has_bead_fields:
        return
    if assigned is not None and decision.get("bead_action") not in {"keep", "close"}:
        raise FinalizerDeclarationError(
            "bead_action is required when a bead is assigned; use keep or close",
            code="commit_bead_action_invalid",
        )
    bead_decision = {
        key: decision[key] for key in _BEAD_DECISION_KEYS if key in decision
    }
    bead_decision.setdefault("repo_id", repo_id)
    bead_decision.setdefault("commit_method", "create_commit")
    bead_decision.pop("bead_status", None)
    if (
        assigned is not None
        and decision.get("bead_action") == "close"
        and repo_id == assigned.primary_repo_obligation_id
    ):
        bead_decision["bead_status"] = _host_close_bead_status(
            assigned.bead_id,
            assigned.primary_repo_obligation_id,
            host_records,
        )
    try:
        validate_finalizer_bead_decision(context, bead_decision)
    except ValueError as exc:
        raise FinalizerDeclarationError(
            str(exc),
            code="commit_bead_action_invalid",
        ) from exc


def _context_assigned_bead(
    context: FinalizerContextWire,
) -> FinalizerAssignedBeadWire | None:
    assigned = context.assigned_bead
    if assigned is not None:
        return assigned
    encoded = finalizer_wire_to_json_dict(context)
    raw = encoded.get("assigned_bead") if isinstance(encoded, dict) else None
    if isinstance(raw, dict):
        return finalizer_assigned_bead_from_dict(raw)
    return None


def _reject_extra_keys(
    data: Mapping[str, Any],
    allowed: set[str],
    action: str,
) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise FinalizerDeclarationError(
            f"{action} decision contains unknown key(s): {', '.join(extra)}",
            code="commit_decision_unknown_key",
        )


def _repository_obligation_paths(
    context: FinalizerContextWire,
) -> dict[str, list[str]]:
    return {
        obligation.obligation_id: list(obligation.paths)
        for obligation in context.obligations
        if obligation.kind == "repository"
    }
