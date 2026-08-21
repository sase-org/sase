"""Turn-bound finalizer declaration context and submission artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from sase.agent.identity import resolve_local_agent_name
from sase.agent.pending_handoff import has_pending_handoff
from sase.core.finalizer_facade import (
    finalizer_json_digest,
    validate_finalizer_context,
    validate_finalizer_submission,
)
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerObligationWire,
    FinalizerPayloadRequirementWire,
    FinalizerPlanWire,
    finalizer_context_from_dict,
    finalizer_plan_from_dict,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.declaration_format import format_context_pretty
from sase.finalizers.plan import load_persisted_finalizer_plan
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import dirty_path_fingerprints
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.memory.locks import locked_file
from sase.telemetry.metrics import (
    FINALIZER_RECOVERIES,
    FINALIZER_SELECTED,
    FINALIZER_SUBMISSIONS,
)
from sase.workflows.commit.message_validation import (
    check_commit_message,
    load_commit_message_policy,
)

SASE_FINAL_TURN_NONCE_ENV = "SASE_FINAL_TURN_NONCE"

FINAL_CONTEXT_FILENAME = "final_context.json"
FINAL_SUBMISSION_FILENAME = "final_submission.json"
FINAL_SUBMISSION_ATTEMPTS_FILENAME = "final_submission_attempts.jsonl"
FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME = "final_declaration_recovery_prompt.md"
FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME = "final_declaration_recovery_response.md"

MAX_FINAL_SUBMISSION_BYTES = 256 * 1024
MAX_ATTEMPT_RECORDS = 50


class FinalizerDeclarationError(RuntimeError):
    """Raised when a finalizer declaration command cannot complete."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FinalContextPublication:
    """One published finalizer context artifact."""

    payload: dict[str, Any]
    context: FinalizerContextWire
    path: Path

    @property
    def submission_required(self) -> bool:
        return _context_requires_submission(self.context)


def mint_finalizer_turn_nonce() -> str:
    """Mint and publish a nonce for the active provider turn."""

    nonce = secrets.token_urlsafe(32)
    os.environ[SASE_FINAL_TURN_NONCE_ENV] = nonce
    return nonce


def append_finalizer_end_turn_instructions(prompt: str) -> str:
    """Append end-of-turn final-declaration instructions to a provider prompt."""

    block = """## SASE Final Declaration

Before your final response in this normal SASE turn, use your `/sase_final` skill as
the last action. It will call `sase final context`, inspect any selected finalizers and
repository obligations, and submit one atomic declaration with `sase final submit` when
the host requires one.

After a successful `sase final submit`, do not make more file or repository changes in
this turn. If the declaration command reports validation errors, repair the manifest
and resubmit before returning when possible. Intentional handoff commands such as plan,
monitor, pipe, and questions terminate the runner mechanically and do not need a final
declaration."""
    return f"{prompt.rstrip()}\n\n{block}\n"


def publish_final_context(
    *,
    artifacts_dir: str | None = None,
) -> FinalContextPublication:
    """Recompute, validate, and atomically publish the current finalizer context."""

    root = _require_artifacts_dir(artifacts_dir, "sase final context")
    plan = _load_plan(root)
    run_id, agent_id, turn_nonce = _run_identity(root, "sase final context")
    dirty_state = _collect_dirty_state(root)
    requirements, obligations = _build_context_requirements(plan, dirty_state)

    context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id=run_id,
        agent_id=agent_id,
        turn_nonce=turn_nonce,
        plan_digest=plan.plan_digest,
        requirements=requirements,
        obligations=obligations,
    )
    context_digest = validate_finalizer_context(plan, context)
    context = replace(context, context_digest=context_digest)
    payload = _context_payload(plan, context)
    _record_selected_metrics(payload)

    path = root / FINAL_CONTEXT_FILENAME
    with locked_file(root / f"{FINAL_CONTEXT_FILENAME}.lock", fcntl.LOCK_EX):
        _write_json_atomic(path, payload)
    return FinalContextPublication(payload=payload, context=context, path=path)


def submit_final_manifest(
    manifest: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish one finalizer declaration manifest."""

    root = _require_artifacts_dir(artifacts_dir, "sase final submit")
    content_digest = _safe_value_digest(manifest)

    with locked_file(root / f"{FINAL_SUBMISSION_FILENAME}.lock", fcntl.LOCK_EX):
        try:
            plan = _load_plan(root)
            context = _load_latest_context(root)
            envelope = _normalize_submission_envelope(manifest)
            validation = validate_finalizer_submission(plan, context, envelope)
            _validate_provider_payloads(plan, context, envelope)
        except FinalizerDeclarationError as exc:
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=exc.code,
                message=str(exc),
                content_digest=content_digest,
            )
            raise
        except Exception as exc:
            wrapped = FinalizerDeclarationError(str(exc), code="core_validation_failed")
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=wrapped.code,
                message=str(wrapped),
                content_digest=content_digest,
            )
            raise wrapped from exc

        submission_payload = {
            "schema_version": 1,
            "accepted_at": _now_iso(),
            "submission": envelope,
            "validation": finalizer_wire_to_json_dict(validation),
        }
        _append_attempt_record_locked(
            root,
            accepted=True,
            code="accepted",
            message="accepted finalizer declaration",
            content_digest=content_digest,
            submission_digest=validation.submission_digest,
            accepted_instances=tuple(validation.accepted_instances),
        )
        _write_json_atomic(root / FINAL_SUBMISSION_FILENAME, submission_payload)
        return submission_payload


def read_final_manifest_from_path(path: str) -> Mapping[str, Any]:
    """Read one JSON manifest from a path or stdin marker."""

    if path == "-":
        import sys

        raw = sys.stdin.buffer.read(MAX_FINAL_SUBMISSION_BYTES + 1)
    else:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            _record_attempt_best_effort(
                code="manifest_read_failed",
                message=f"could not read final declaration manifest: {exc}",
                content_digest=_raw_digest(path.encode("utf-8", errors="replace")),
            )
            raise FinalizerDeclarationError(
                f"could not read final declaration manifest: {exc}",
                code="manifest_read_failed",
            ) from exc
    if len(raw) > MAX_FINAL_SUBMISSION_BYTES:
        _record_attempt_best_effort(
            code="manifest_too_large",
            message="final declaration manifest is too large",
            content_digest=_raw_digest(raw),
        )
        raise FinalizerDeclarationError(
            "final declaration manifest is too large",
            code="manifest_too_large",
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _record_attempt_best_effort(
            code="manifest_invalid_json",
            message=f"final declaration manifest is not valid JSON: {exc}",
            content_digest=_raw_digest(raw),
        )
        raise FinalizerDeclarationError(
            f"final declaration manifest is not valid JSON: {exc}",
            code="manifest_invalid_json",
        ) from exc
    if not isinstance(parsed, Mapping):
        _record_attempt_best_effort(
            code="manifest_not_object",
            message="final declaration manifest must be a JSON object",
            content_digest=_safe_value_digest({"manifest": parsed}),
        )
        raise FinalizerDeclarationError(
            "final declaration manifest must be a JSON object",
            code="manifest_not_object",
        )
    return parsed


def final_submission_is_current(*, artifacts_dir: str | None = None) -> bool:
    """Return whether the latest accepted submission satisfies the latest context."""

    root = _require_artifacts_dir(artifacts_dir, "finalizer declaration check")
    plan = _load_plan(root)
    context = _load_latest_context(root)
    if not _context_requires_submission(context):
        return True
    try:
        submission = _load_latest_submission(root)
        envelope = _normalize_submission_envelope(submission["submission"])
        validate_finalizer_submission(plan, context, envelope)
        _validate_provider_payloads(plan, context, envelope)
    except Exception:
        return False
    return True


def ensure_final_declaration_or_recover(
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: LLMInvocationOptions | None = None,
) -> InvokeResult:
    """Run one declaration-recovery turn when required submission is absent."""

    if has_pending_handoff(artifacts_dir):
        FINALIZER_RECOVERIES.labels(kind="declaration", result="handoff").inc()
        return invoke_result

    context = publish_final_context(artifacts_dir=artifacts_dir)
    if not context.submission_required or final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        FINALIZER_RECOVERIES.labels(kind="declaration", result="not_required").inc()
        return invoke_result

    previous_nonce = os.environ.get(SASE_FINAL_TURN_NONCE_ENV)
    recovery_nonce = mint_finalizer_turn_nonce()
    try:
        prompt = _declaration_recovery_prompt(context)
        root = _require_artifacts_dir(
            artifacts_dir,
            "finalizer declaration recovery",
        )
        _write_text_atomic(root / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME, prompt)
        follow_up = provider.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )
        _write_text_atomic(
            root / FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME,
            follow_up.content,
        )
        accumulated = InvokeResult(
            content=append_response(invoke_result.content, follow_up.content),
            usage=merge_usage(invoke_result.usage, follow_up.usage),
        )
        if not _latest_context_matches_nonce(root, recovery_nonce):
            raise RuntimeError(
                "Finalizer declaration recovery failed: no fresh context was "
                "published for the recovery turn"
            )
        if not final_submission_is_current(artifacts_dir=artifacts_dir):
            raise RuntimeError(
                "Finalizer declaration recovery failed: required declaration "
                "is still missing or invalid"
            )
        FINALIZER_RECOVERIES.labels(kind="declaration", result="success").inc()
        return accumulated
    except Exception:
        FINALIZER_RECOVERIES.labels(kind="declaration", result="failed").inc()
        raise
    finally:
        if previous_nonce is None:
            os.environ.pop(SASE_FINAL_TURN_NONCE_ENV, None)
        else:
            os.environ[SASE_FINAL_TURN_NONCE_ENV] = previous_nonce


def _require_artifacts_dir(value: str | None, command: str) -> Path:
    raw = value or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        raise FinalizerDeclarationError(
            f"{command} requires SASE_ARTIFACTS_DIR",
            code="missing_artifacts_dir",
        )
    return Path(raw).expanduser().resolve(strict=False)


def _run_identity(root: Path, command: str) -> tuple[str, str, str]:
    run_id = (os.environ.get("SASE_AGENT_TIMESTAMP") or "").strip()
    identity_env = dict(os.environ)
    identity_env["SASE_ARTIFACTS_DIR"] = str(root)
    agent_id = resolve_local_agent_name(identity_env) or ""
    turn_nonce = (os.environ.get(SASE_FINAL_TURN_NONCE_ENV) or "").strip()
    missing: list[str] = []
    if not run_id:
        missing.append("SASE_AGENT_TIMESTAMP")
    if not agent_id:
        missing.append("SASE_AGENT_NAME or agent_meta.json name")
    if not turn_nonce:
        missing.append(SASE_FINAL_TURN_NONCE_ENV)
    if missing:
        raise FinalizerDeclarationError(
            f"{command} requires active finalizer turn metadata: " + ", ".join(missing),
            code="missing_turn_metadata",
        )
    return run_id, agent_id, turn_nonce


def _load_plan(root: Path) -> FinalizerPlanWire:
    payload = load_persisted_finalizer_plan(str(root))
    if not payload:
        raise FinalizerDeclarationError(
            "finalizer plan artifact is missing",
            code="missing_finalizer_plan",
        )
    plan = payload.get("plan")
    if not isinstance(plan, Mapping):
        raise FinalizerDeclarationError(
            "finalizer plan artifact is malformed",
            code="malformed_finalizer_plan",
        )
    try:
        return finalizer_plan_from_dict(dict(plan))
    except Exception as exc:
        raise FinalizerDeclarationError(
            f"finalizer plan artifact is invalid: {exc}",
            code="malformed_finalizer_plan",
        ) from exc


def _collect_dirty_state(root: Path) -> DirtyState:
    return collect_dirty_state(
        resolve_finalizer_project_dir(),
        artifact_root=root,
    )


def _build_context_requirements(
    plan: FinalizerPlanWire,
    dirty_state: DirtyState,
) -> tuple[list[FinalizerPayloadRequirementWire], list[FinalizerObligationWire]]:
    requirements: list[FinalizerPayloadRequirementWire] = []
    obligations: list[FinalizerObligationWire] = []
    repository_obligations: list[FinalizerObligationWire] | None = None

    for entry in plan.entries:
        if entry.provider_ref == "builtin@commit":
            if repository_obligations is None:
                repository_obligations = [
                    _repository_obligation(repo) for repo in dirty_state.repos
                ]
                obligations.extend(repository_obligations)
            trigger = "dirty_repository" if repository_obligations else "not_triggered"
            requirements.append(
                FinalizerPayloadRequirementWire(
                    instance_id=entry.instance_id,
                    trigger=trigger,
                    submission_required=bool(repository_obligations),
                    requirement_digest=finalizer_json_digest(
                        {
                            "instance_id": entry.instance_id,
                            "trigger": trigger,
                            "repositories": [
                                {
                                    "id": obligation.obligation_id,
                                    "digest": obligation.digest,
                                }
                                for obligation in repository_obligations
                            ],
                        }
                    ),
                )
            )
            continue
        if entry.provider_ref == "builtin@command":
            requirements.append(
                FinalizerPayloadRequirementWire(
                    instance_id=entry.instance_id,
                    trigger="always",
                    submission_required=False,
                    requirement_digest=finalizer_json_digest(
                        {
                            "instance_id": entry.instance_id,
                            "trigger": "always",
                            "submission_required": False,
                        }
                    ),
                )
            )
            continue
        requirements.append(
            FinalizerPayloadRequirementWire(
                instance_id=entry.instance_id,
                trigger="provider_requested",
                submission_required=True,
                requirement_digest=finalizer_json_digest(
                    {
                        "instance_id": entry.instance_id,
                        "trigger": "provider_requested",
                    }
                ),
            )
        )
    return requirements, obligations


def _repository_obligation(repo: DirtyRepo) -> FinalizerObligationWire:
    repo_id = _repository_obligation_id(repo)
    paths = list(repo.changed_files)
    state_digest = _repository_state_digest(repo_id, repo, paths)
    return FinalizerObligationWire(
        obligation_id=repo_id,
        kind="repository",
        display_name=_repository_display_name(repo),
        paths=paths,
        digest=state_digest,
    )


def _repository_obligation_id(repo: DirtyRepo) -> str:
    raw = json.dumps(
        {
            "kind": repo.kind,
            "name": repo.name,
            "path": repo.path,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"repo-{hashlib.sha256(raw).hexdigest()[:12]}"


def _repository_state_digest(
    repo_id: str,
    repo: DirtyRepo,
    paths: Sequence[str],
) -> str:
    fingerprints = dirty_path_fingerprints(repo.path)
    return finalizer_json_digest(
        {
            "repo_id": repo_id,
            "kind": repo.kind,
            "name": repo.name,
            "paths": list(paths),
            "fingerprints": {
                path: list(fingerprints[path]) for path in paths if path in fingerprints
            },
        }
    )


def _repository_display_name(repo: DirtyRepo) -> str:
    if repo.kind == "main":
        return "main"
    if repo.name:
        return f"{repo.kind}:{repo.name}"
    return repo.kind


def _context_payload(
    plan: FinalizerPlanWire,
    context: FinalizerContextWire,
) -> dict[str, Any]:
    requirement_by_id = {item.instance_id: item for item in context.requirements}
    selected = []
    for entry in plan.entries:
        requirement = requirement_by_id.get(entry.instance_id)
        selected.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "trigger": requirement.trigger if requirement else "not_triggered",
                "submission_required": (
                    requirement.submission_required if requirement else False
                ),
                "policy": finalizer_wire_to_json_dict(entry.policy),
            }
        )
    return {
        "schema_version": 1,
        "issued_at": _now_iso(),
        "context": finalizer_wire_to_json_dict(context),
        "selected_instances": selected,
        "submission_required": _context_requires_submission(context),
        "manifest_template": _manifest_template(context),
    }


def _record_selected_metrics(payload: Mapping[str, Any]) -> None:
    selected = payload.get("selected_instances")
    if not isinstance(selected, list):
        return
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        instance_id = item.get("instance_id")
        provider_ref = item.get("provider_ref")
        trigger = item.get("trigger")
        if not (
            isinstance(instance_id, str)
            and isinstance(provider_ref, str)
            and isinstance(trigger, str)
        ):
            continue
        FINALIZER_SELECTED.labels(
            provider=provider_ref,
            instance=instance_id,
            trigger=trigger,
        ).inc()


def _manifest_template(context: FinalizerContextWire) -> dict[str, Any]:
    payloads: list[dict[str, Any]] = []
    repo_ids = [
        obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    ]
    for requirement in context.requirements:
        if not requirement.submission_required:
            continue
        payload: Any
        if requirement.trigger == "dirty_repository":
            payload = {
                "repositories": [
                    {
                        "repo_id": repo_id,
                        "action": "commit",
                        "message": "feat(scope): describe the completed work",
                    }
                    for repo_id in repo_ids
                ]
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


def _load_latest_context(root: Path) -> FinalizerContextWire:
    try:
        payload = json.loads((root / FINAL_CONTEXT_FILENAME).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            "finalizer context has not been published",
            code="missing_final_context",
        ) from exc
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("context"), Mapping
    ):
        raise FinalizerDeclarationError(
            "finalizer context artifact is malformed",
            code="malformed_final_context",
        )
    try:
        return finalizer_context_from_dict(dict(payload["context"]))
    except Exception as exc:
        raise FinalizerDeclarationError(
            f"finalizer context artifact is invalid: {exc}",
            code="malformed_final_context",
        ) from exc


def _load_latest_submission(root: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / FINAL_SUBMISSION_FILENAME).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            "finalizer submission has not been accepted",
            code="missing_final_submission",
        ) from exc
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("submission"), Mapping
    ):
        raise FinalizerDeclarationError(
            "finalizer submission artifact is malformed",
            code="malformed_final_submission",
        )
    return payload


def _normalize_submission_envelope(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw: Any = manifest.get("submission") if "submission" in manifest else manifest
    if not isinstance(raw, Mapping):
        raise FinalizerDeclarationError(
            "final declaration submission must be a JSON object",
            code="submission_not_object",
        )
    envelope = dict(raw)
    payloads = envelope.get("payloads")
    if not isinstance(payloads, list):
        raise FinalizerDeclarationError(
            "final declaration submission payloads must be a list",
            code="submission_payloads_not_list",
        )
    normalized_payloads: list[dict[str, Any]] = []
    for index, item in enumerate(payloads):
        if not isinstance(item, Mapping):
            raise FinalizerDeclarationError(
                f"final declaration payload #{index + 1} must be an object",
                code="submission_payload_not_object",
            )
        normalized = dict(item)
        if "payload" not in normalized:
            raise FinalizerDeclarationError(
                f"final declaration payload #{index + 1} is missing payload",
                code="submission_payload_missing",
            )
        if normalized.get("payload_digest") is None:
            normalized["payload_digest"] = finalizer_json_digest(normalized["payload"])
        normalized_payloads.append(normalized)
    envelope["payloads"] = normalized_payloads
    return envelope


def _validate_provider_payloads(
    plan: FinalizerPlanWire,
    context: FinalizerContextWire,
    envelope: Mapping[str, Any],
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
            _validate_commit_payload(context, payload)


def _validate_commit_payload(
    context: FinalizerContextWire,
    payload: Any,
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
    expected = {
        obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    }
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
            _validate_commit_decision(repo_id, decision)
        elif action == "refuse":
            _validate_refusal_decision(repo_id, decision)
        else:
            raise FinalizerDeclarationError(
                f"commit repository decision for {repo_id} has invalid action",
                code="commit_action_invalid",
            )
    missing = expected - seen
    if missing:
        raise FinalizerDeclarationError(
            "commit finalizer payload is missing repository decision(s): "
            + ", ".join(sorted(missing)),
            code="commit_repo_decision_missing",
        )


def _validate_commit_decision(
    repo_id: str,
    decision: Mapping[str, Any],
) -> None:
    _reject_extra_keys(decision, {"repo_id", "action", "message"}, "commit")
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
    rejection = check_commit_message(message, load_commit_message_policy())
    if rejection is not None:
        raise FinalizerDeclarationError(
            f"commit decision for {repo_id} has a non-conventional message",
            code="commit_message_invalid",
        )


def _validate_refusal_decision(
    repo_id: str,
    decision: Mapping[str, Any],
) -> None:
    _reject_extra_keys(decision, {"repo_id", "action", "reason"}, "refuse")
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise FinalizerDeclarationError(
            f"refusal decision for {repo_id} requires a nonblank reason",
            code="commit_refusal_reason_missing",
        )
    if len(reason) > 4000:
        raise FinalizerDeclarationError(
            f"refusal decision for {repo_id} has an oversized reason",
            code="commit_refusal_reason_too_large",
        )


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


def _context_requires_submission(context: FinalizerContextWire) -> bool:
    return any(requirement.submission_required for requirement in context.requirements)


def _latest_context_matches_nonce(root: Path, nonce: str) -> bool:
    try:
        return _load_latest_context(root).turn_nonce == nonce
    except FinalizerDeclarationError:
        return False


def _declaration_recovery_prompt(context: FinalContextPublication) -> str:
    return (
        "A required SASE finalizer declaration was missing or stale after your "
        "normal response.\n\n"
        "This is the single declaration-recovery turn. Do not perform unrelated "
        "work, do not mutate repositories, and do not answer the user yet. Use "
        "your `/sase_final` skill now; it must publish a fresh context for this "
        "turn and submit one valid declaration for every required finalizer "
        "payload. After the declaration succeeds, return briefly.\n\n"
        f"Current required context digest: {context.context.context_digest}\n"
    )


def _append_attempt_record_locked(
    root: Path,
    *,
    accepted: bool,
    code: str,
    message: str,
    content_digest: str,
    submission_digest: str | None = None,
    accepted_instances: Sequence[str] = (),
) -> None:
    FINALIZER_SUBMISSIONS.labels(
        result="accepted" if accepted else "rejected",
        code=code,
    ).inc()
    record = {
        "schema_version": 1,
        "recorded_at": _now_iso(),
        "accepted": accepted,
        "code": code,
        "message": message[:500],
        "content_digest": content_digest,
        "submission_digest": submission_digest,
        "accepted_instances": list(accepted_instances),
    }
    path = root / FINAL_SUBMISSION_ATTEMPTS_FILENAME
    records: list[Mapping[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if isinstance(parsed, Mapping):
                records.append(parsed)
    except (OSError, json.JSONDecodeError):
        records = []
    records = [*records[-(MAX_ATTEMPT_RECORDS - 1) :], record]
    text = "".join(json.dumps(item, sort_keys=True) + "\n" for item in records)
    _write_text_atomic(path, text)


def _record_attempt_best_effort(
    *,
    code: str,
    message: str,
    content_digest: str,
) -> None:
    try:
        root = _require_artifacts_dir(None, "sase final submit")
        with locked_file(root / f"{FINAL_SUBMISSION_FILENAME}.lock", fcntl.LOCK_EX):
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=code,
                message=message,
                content_digest=content_digest,
            )
    except Exception:
        return


def _safe_value_digest(value: Mapping[str, Any]) -> str:
    try:
        return finalizer_json_digest(dict(value))
    except Exception:
        raw = repr(value).encode("utf-8", errors="replace")
        return _raw_digest(raw)


def _raw_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "FINAL_CONTEXT_FILENAME",
    "FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME",
    "FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME",
    "FINAL_SUBMISSION_ATTEMPTS_FILENAME",
    "FINAL_SUBMISSION_FILENAME",
    "FinalContextPublication",
    "FinalizerDeclarationError",
    "SASE_FINAL_TURN_NONCE_ENV",
    "append_finalizer_end_turn_instructions",
    "ensure_final_declaration_or_recover",
    "final_submission_is_current",
    "format_context_pretty",
    "mint_finalizer_turn_nonce",
    "publish_final_context",
    "read_final_manifest_from_path",
    "submit_final_manifest",
]
