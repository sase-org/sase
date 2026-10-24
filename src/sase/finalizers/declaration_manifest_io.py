"""Finalizer declaration manifest I/O, envelope, and attempt helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.core.finalizer_facade import finalizer_json_digest
from sase.core.finalizer_wire import (
    FinalizerContextWire,
    finalizer_context_from_dict,
)
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    write_text_atomic,
)
from sase.telemetry.metrics import FINALIZER_SUBMISSIONS

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


def commit_bead_actions(
    manifest: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Return ``(has_commit, bead_actions)`` for commit decisions in *manifest*.

    Accepts a finalizer submission envelope (``{"submission": {...}}``), a
    declaration with ``payloads``, or a prepare wrapper with ``declaration``.
    ``bead_actions`` preserves first-seen order and only records ``keep``
    and ``close``.
    """

    source = _commit_bead_actions_source(manifest)
    payloads = source.get("payloads") if source is not None else None
    if not isinstance(payloads, list):
        return False, []
    has_commit = False
    bead_actions: list[str] = []
    for entry in payloads:
        payload = entry.get("payload") if isinstance(entry, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            if not isinstance(decision, Mapping):
                continue
            if decision.get("action") != "commit":
                continue
            has_commit = True
            bead_action = decision.get("bead_action")
            if isinstance(bead_action, str) and bead_action in {"keep", "close"}:
                if bead_action not in bead_actions:
                    bead_actions.append(bead_action)
    return has_commit, bead_actions


def _commit_bead_actions_source(
    manifest: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(manifest, Mapping):
        return None
    if "payloads" in manifest:
        return manifest
    submission = manifest.get("submission")
    if isinstance(submission, Mapping) and "payloads" in submission:
        return submission
    declaration = manifest.get("declaration")
    if isinstance(declaration, Mapping):
        return declaration
    return manifest


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
    write_text_atomic(path, text)


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
