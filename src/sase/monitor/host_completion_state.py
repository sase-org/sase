"""Host-completion snapshots, declaration install, and receipt completeness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
)
from sase.core.continuation_facade import evaluate_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.finalizer_wire import FINALIZER_WIRE_SCHEMA_VERSION, FinalizerPlanWire
from sase.finalizers.artifacts import FINALIZER_RESULT_FILENAME
from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.controller import FinalizerControllerError
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.declaration_store import load_accepted_host_repositories
from sase.finalizers.plan import (
    authenticate_resolved_finalizer_plan,
    resolve_and_persist_finalizer_plan,
)
from sase.finalizers.prepare import observe_completion_repositories
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF, BUILTIN_PROVIDER_REFS
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.monitor.output import OutputCapture
from sase.xprompt.directives import PromptDirectives

FINALIZING_STATUS = "finalizing"
RECOVERY_STATUS = "recovery"


@dataclass(frozen=True, slots=True)
class _ExecutionSnapshot:
    """Recomputed host context used at eligibility and immediately before execute."""

    plan: FinalizerPlanWire
    observations: list[dict[str, Any]]
    publication: Any
    obligation_ids: tuple[str, ...]
    observation_fingerprint: tuple[tuple[str, str, str, str], ...]


def install_prepared_declaration(
    intent: Mapping[str, Any],
    artifacts_dir: str,
    publication: Any,
) -> None:
    """Submit the prepared payloads against the current host-issued context."""

    declaration = deepcopy(intent.get("declaration") or {})
    if not isinstance(declaration, dict):
        raise FinalizerDeclarationError(
            "prepared declaration is not an object",
            code="malformed_completion_intent",
        )
    context = publication.context
    template: dict[str, Any] = {}
    payload = getattr(publication, "payload", None)
    if isinstance(payload, Mapping):
        raw_template = payload.get("manifest_template")
        if isinstance(raw_template, Mapping):
            template = dict(raw_template)
    payloads = declaration.get("payloads")
    if not isinstance(payloads, list):
        payloads = template.get("payloads") or []
    envelope = {
        "schema_version": declaration.get("schema_version")
        or template.get("schema_version")
        or FINALIZER_WIRE_SCHEMA_VERSION,
        "run_id": _context_str(context, "run_id")
        or template.get("run_id")
        or os.environ.get("SASE_AGENT_TIMESTAMP")
        or Path(artifacts_dir).name,
        "agent_id": _context_str(context, "agent_id")
        or template.get("agent_id")
        or os.environ.get("SASE_AGENT_NAME")
        or "",
        "turn_nonce": _context_str(context, "turn_nonce")
        or template.get("turn_nonce")
        or os.environ.get(SASE_FINAL_TURN_NONCE_ENV)
        or "",
        "plan_digest": _context_str(context, "plan_digest")
        or template.get("plan_digest")
        or "",
        "context_digest": _context_str(context, "context_digest")
        or template.get("context_digest")
        or "",
        "payloads": payloads,
    }
    if not envelope["plan_digest"]:
        plan = authenticate_resolved_finalizer_plan(artifacts_dir)
        envelope["plan_digest"] = plan.plan_digest
    os.environ.setdefault("SASE_AGENT_TIMESTAMP", Path(artifacts_dir).name)
    os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
    submit_final_manifest(envelope, artifacts_dir=artifacts_dir)


def snapshot_execution_context(
    artifacts_dir: str,
    meta: Mapping[str, Any],
) -> _ExecutionSnapshot:
    """Recompute plan, observations, obligations, and fingerprints."""

    del meta
    plan = ensure_finalizer_plan(artifacts_dir)
    observations = [
        dict(item)
        for item in observe_completion_repositories(Path(artifacts_dir))
        if isinstance(item, Mapping)
    ]
    publication = publish_final_context(artifacts_dir=artifacts_dir)
    obligation_ids = tuple(
        str(item.obligation_id)
        for item in publication.context.obligations
        if getattr(item, "kind", None) == "repository"
    )
    return _ExecutionSnapshot(
        plan=plan,
        observations=observations,
        publication=publication,
        obligation_ids=obligation_ids,
        observation_fingerprint=_observation_fingerprint(observations),
    )


def evaluate_intent(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    *,
    intent: Mapping[str, Any],
    snapshot: _ExecutionSnapshot,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Evaluate the bound intent against the current host snapshot."""

    from sase.monitor.diagnostics import diagnostic_manifest

    stages = list((diagnostic_manifest(artifacts_dir) or {}).get("stages") or [])
    return evaluate_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": intent,
            "outcome": policy_outcome(monitor_state),
            "exit_code": exit_code,
            "command": _command_argv(meta),
            "observations": snapshot.observations,
            "stages": stages,
            "executors": executor_capabilities(snapshot.plan),
            "workspace_identity": workspace_identity(meta),
            "original_workspace_identity": _original_workspace_identity(intent, meta),
            "degraded_workspace": bool(meta.get("monitor_followup_degraded_reason")),
            "current_plan_digest": snapshot.plan.plan_digest,
            "current_obligation_ids": list(snapshot.obligation_ids),
            "substitutions": {
                "duration": _format_duration(elapsed_seconds),
                "evidence_ref": str(meta.get("monitor_diagnostic_manifest_ref") or ""),
            },
        }
    )


def ensure_finalizer_plan(artifacts_dir: str) -> FinalizerPlanWire:
    """Return the authenticated plan, resolving one if needed."""

    try:
        return authenticate_resolved_finalizer_plan(artifacts_dir)
    except Exception:
        resolved = resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=artifacts_dir
        )
        if resolved is None:
            raise FinalizerControllerError(
                "no-model host completion could not resolve a finalizer plan",
                code="no_model_missing_plan",
            ) from None
        return resolved.plan


def executor_capabilities(plan: FinalizerPlanWire) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for entry in plan.entries:
        builtin = entry.provider_ref in BUILTIN_PROVIDER_REFS
        capabilities.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "headless": builtin,
                "durable_replay": builtin,
                "requires_model": not builtin,
            }
        )
    return capabilities


def intent_artifacts_dir(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    project_name: str | None,
) -> str:
    parent = meta.get("parent_timestamp")
    if project_name and isinstance(parent, str) and parent:
        starter = canonical_agent_artifact_path(
            project_name, ACE_RUN_WORKFLOW_DIR, parent
        )
        if starter.is_dir():
            return str(starter)
    return artifacts_dir


def _command_argv(meta: Mapping[str, Any]) -> list[str]:
    raw = meta.get("monitor_execution_argv")
    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes) and raw:
        return [str(part) for part in raw]
    command = str(meta.get("monitor_command") or "")
    return command.split() if command else []


def workspace_identity(meta: Mapping[str, Any]) -> str:
    return str(
        meta.get("continuation_workspace_ref")
        or meta.get("workspace_dir")
        or meta.get("workspace_num")
        or "unknown"
    )


def _original_workspace_identity(
    intent: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> str:
    creator = (intent.get("seal") or {}).get("creator") or {}
    workspace_id = creator.get("workspace_id")
    if workspace_id:
        current = str(meta.get("workspace_num") or "")
        if current and current == str(workspace_id):
            return workspace_identity(meta)
        return str(workspace_id)
    return workspace_identity(meta)


def policy_outcome(monitor_state: str) -> str:
    if monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}:
        return monitor_state
    return "unknown"


def _format_duration(elapsed_seconds: float) -> str:
    total = max(0, int(round(elapsed_seconds)))
    minutes, seconds = divmod(total, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def record_status(
    artifacts_dir: str,
    meta: dict[str, Any],
    status: str,
    *,
    reason: str | None = None,
) -> None:
    meta["monitor_host_completion_status"] = status
    update_meta_field(artifacts_dir, "monitor_host_completion_status", status)
    if reason:
        meta["monitor_host_completion_reason"] = reason
        update_meta_field(artifacts_dir, "monitor_host_completion_reason", reason)


def recovery_launch_kwargs(
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    project_name: str | None,
    timeout_kind: str | None,
    transfer_from_pid: int | None,
) -> dict[str, Any]:
    del project_name
    return {
        "monitor_state": monitor_state,
        "exit_code": exit_code,
        "elapsed_seconds": elapsed_seconds,
        "capture": capture,
        "timeout_kind": timeout_kind,
        "transfer_from_pid": transfer_from_pid,
    }


def required_commit_repo_ids(intent: Mapping[str, Any]) -> list[str]:
    decisions = intent.get("repository_decisions")
    ids: list[str] = []
    if isinstance(decisions, list):
        for decision in decisions:
            if (
                isinstance(decision, Mapping)
                and decision.get("action") == "commit"
                and decision.get("repo_id")
            ):
                ids.append(str(decision["repo_id"]))
        if ids:
            return ids
    declaration = intent.get("declaration") or {}
    if not isinstance(declaration, Mapping):
        return []
    payloads = declaration.get("payloads") or []
    if not isinstance(payloads, list):
        return []
    for item in payloads:
        if not isinstance(item, Mapping):
            continue
        body = item.get("payload") or {}
        if not isinstance(body, Mapping):
            continue
        repositories = body.get("repositories") or []
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            if (
                isinstance(decision, Mapping)
                and decision.get("action") == "commit"
                and decision.get("repo_id")
            ):
                ids.append(str(decision["repo_id"]))
    return ids


def _successful_receipt_repo_ids(artifacts_dir: str) -> set[str]:
    markers = load_commit_results(artifact_root(artifacts_dir))
    records = load_accepted_host_repositories(Path(artifacts_dir))
    path_to_id = {
        normalize_path(record.path): record.obligation_id for record in records
    }
    found: set[str] = set()
    for marker in markers:
        if not isinstance(marker, Mapping):
            continue
        if not _marker_is_successful(marker):
            continue
        repo_id = marker.get("repo_id")
        if isinstance(repo_id, str) and repo_id:
            found.add(repo_id)
        cwd = marker.get("cwd")
        if isinstance(cwd, str) and normalize_path(cwd) in path_to_id:
            found.add(path_to_id[normalize_path(cwd)])
    return found


def _marker_is_successful(marker: Mapping[str, Any]) -> bool:
    if marker.get("result") != "ok":
        return False
    return bool(marker.get("commit_sha") or marker.get("sha"))


def _has_any_successful_receipt(artifacts_dir: str) -> bool:
    markers = load_commit_results(artifact_root(artifacts_dir))
    return any(
        isinstance(marker, Mapping) and _marker_is_successful(marker)
        for marker in markers
    )


def _later_finalizer_ids(plan: FinalizerPlanWire) -> list[str]:
    return [
        entry.instance_id
        for entry in plan.entries
        if entry.provider_ref != BUILTIN_COMMIT_PROVIDER_REF
    ]


def _load_aggregate_result(artifacts_dir: str) -> dict[str, Any] | None:
    path = Path(artifacts_dir) / FINALIZER_RESULT_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _later_finalizers_complete(artifacts_dir: str, plan: FinalizerPlanWire) -> bool:
    required = _later_finalizer_ids(plan)
    if not required:
        return True
    payload = _load_aggregate_result(artifacts_dir)
    if payload is None or payload.get("status") != "success":
        return False
    instances = payload.get("instances") or []
    by_id = {
        item.get("instance_id"): item for item in instances if isinstance(item, Mapping)
    }
    return all(
        isinstance(by_id.get(instance_id), Mapping)
        and by_id[instance_id].get("status") == "success"
        for instance_id in required
    )


def _all_required_commits_succeeded(
    intent: Mapping[str, Any], artifacts_dir: str
) -> bool:
    required = required_commit_repo_ids(intent)
    if not required:
        return True
    succeeded = _successful_receipt_repo_ids(artifacts_dir)
    return all(repo_id in succeeded for repo_id in required)


def all_required_actions_complete(
    intent: Mapping[str, Any],
    plan: FinalizerPlanWire,
    artifacts_dir: str,
) -> bool:
    return _all_required_commits_succeeded(
        intent, artifacts_dir
    ) and _later_finalizers_complete(artifacts_dir, plan)


def can_finish_without_rerun(
    intent: Mapping[str, Any],
    plan: FinalizerPlanWire,
    artifacts_dir: str,
) -> bool:
    if not (
        _has_any_successful_receipt(artifacts_dir)
        or _load_aggregate_result(artifacts_dir) is not None
    ):
        return False
    return all_required_actions_complete(intent, plan, artifacts_dir)


def should_resume_outstanding(
    receipt: Mapping[str, Any] | None,
    intent: Mapping[str, Any],
    plan: FinalizerPlanWire,
    artifacts_dir: str,
) -> bool:
    if receipt is None:
        return False
    if receipt.get("status") not in {FINALIZING_STATUS, RECOVERY_STATUS}:
        return False
    if ambiguous_commit(receipt, artifacts_dir):
        return False
    if not _has_any_successful_receipt(artifacts_dir):
        return False
    return not all_required_actions_complete(intent, plan, artifacts_dir)


def new_obligation_ids(
    intent: Mapping[str, Any], current_ids: Sequence[str]
) -> list[str]:
    decided = set(required_commit_repo_ids(intent))
    decisions = intent.get("repository_decisions")
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, Mapping) and decision.get("repo_id"):
                decided.add(str(decision["repo_id"]))
    if not decided:
        return []
    return [repo_id for repo_id in current_ids if repo_id not in decided]


def _observation_fingerprint(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str, str, str], ...]:
    rows = [
        (
            str(item.get("repo_id") or ""),
            str(item.get("head") or ""),
            str(item.get("head_tree") or ""),
            str(item.get("index_tree") or ""),
        )
        for item in observations
        if isinstance(item, Mapping)
    ]
    return tuple(sorted(rows))


def execution_context_drifted(
    before: _ExecutionSnapshot, after: _ExecutionSnapshot
) -> bool:
    return (
        before.plan.plan_digest != after.plan.plan_digest
        or before.observation_fingerprint != after.observation_fingerprint
        or bool(set(after.obligation_ids) - set(before.obligation_ids))
    )


def ambiguous_commit(receipt: Mapping[str, Any] | None, artifacts_dir: str) -> bool:
    if receipt is None:
        return False
    if receipt.get("status") not in {FINALIZING_STATUS, RECOVERY_STATUS}:
        return False
    if receipt.get("ambiguous"):
        return True
    markers = load_commit_results(artifact_root(artifacts_dir))
    return any(
        isinstance(marker, Mapping)
        and marker.get("result") not in {None, "ok"}
        and "sha" not in marker
        and "commit_sha" not in marker
        for marker in markers
    )


def _context_str(context: Any, field: str) -> str:
    value = getattr(context, field, None)
    if isinstance(value, str) and value:
        return value
    return ""
