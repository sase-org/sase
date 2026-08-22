"""Finalizer declaration manifest parsing, validation, and artifact helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.core.finalizer_facade import finalizer_json_digest
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerPlanWire,
    finalizer_context_from_dict,
)
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    write_text_atomic as _write_text_atomic,
)
from sase.telemetry.metrics import FINALIZER_SUBMISSIONS
from sase.workflows.commit.message_validation import (
    check_commit_message,
    load_commit_message_policy,
)

FINAL_CONTEXT_FILENAME = "final_context.json"
FINAL_SUBMISSION_FILENAME = "final_submission.json"
FINAL_SUBMISSION_ATTEMPTS_FILENAME = "final_submission_attempts.jsonl"

MAX_FINAL_SUBMISSION_BYTES = 256 * 1024
MAX_ATTEMPT_RECORDS = 50


def read_final_manifest_from_path(
    path: str,
    *,
    record_attempt: Callable[..., None],
) -> Mapping[str, Any]:
    """Read one JSON manifest from a path or stdin marker."""

    if path == "-":
        import sys

        raw = sys.stdin.buffer.read(MAX_FINAL_SUBMISSION_BYTES + 1)
    else:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            record_attempt(
                code="manifest_read_failed",
                message=f"could not read final declaration manifest: {exc}",
                content_digest=_raw_digest(path.encode("utf-8", errors="replace")),
            )
            raise FinalizerDeclarationError(
                f"could not read final declaration manifest: {exc}",
                code="manifest_read_failed",
            ) from exc
    if len(raw) > MAX_FINAL_SUBMISSION_BYTES:
        record_attempt(
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
        record_attempt(
            code="manifest_invalid_json",
            message=f"final declaration manifest is not valid JSON: {exc}",
            content_digest=_raw_digest(raw),
        )
        raise FinalizerDeclarationError(
            f"final declaration manifest is not valid JSON: {exc}",
            code="manifest_invalid_json",
        ) from exc
    if not isinstance(parsed, Mapping):
        record_attempt(
            code="manifest_not_object",
            message="final declaration manifest must be a JSON object",
            content_digest=safe_value_digest({"manifest": parsed}),
        )
        raise FinalizerDeclarationError(
            "final declaration manifest must be a JSON object",
            code="manifest_not_object",
        )
    return parsed


def manifest_template(context: FinalizerContextWire) -> dict[str, Any]:
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


def load_latest_finalizer_context(root: Path) -> FinalizerContextWire:
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


def load_latest_finalizer_submission(root: Path) -> Mapping[str, Any]:
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


def normalize_submission_envelope(manifest: Mapping[str, Any]) -> dict[str, Any]:
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


def validate_provider_payloads(
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


def context_requires_submission(context: FinalizerContextWire) -> bool:
    return any(requirement.submission_required for requirement in context.requirements)


def append_attempt_record_locked(
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
        "recorded_at": now_iso(),
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


def safe_value_digest(value: Mapping[str, Any]) -> str:
    try:
        return finalizer_json_digest(dict(value))
    except Exception:
        raw = repr(value).encode("utf-8", errors="replace")
        return _raw_digest(raw)


def _raw_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
