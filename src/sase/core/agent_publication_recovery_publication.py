"""Publication retry, accounting, drain, completion, and prompt decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core._agent_publication_recovery_shared import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    require_bool,
    require_int,
    require_str_field,
)
from sase.core.rust import require_rust_binding

PUBLICATION_KIND_RUN = "run"
PUBLICATION_KIND_SESSION = "session"

PUBLICATION_SCOPE_LINKED = "linked"
PUBLICATION_SCOPE_REVISION = "revision"

PROMPT_STATUS_RESTORED = "restored"
PROMPT_STATUS_ALREADY_ARCHIVED = "already_archived"
PROMPT_STATUS_NOT_APPLICABLE = "not_applicable"
PROMPT_STATUS_UNAVAILABLE = "unavailable"
PROMPT_STATUS_FAILED = "failed"

_KINDS = frozenset({PUBLICATION_KIND_RUN, PUBLICATION_KIND_SESSION})
_PROMPT_STATUSES = frozenset(
    {
        PROMPT_STATUS_RESTORED,
        PROMPT_STATUS_ALREADY_ARCHIVED,
        PROMPT_STATUS_NOT_APPLICABLE,
        PROMPT_STATUS_UNAVAILABLE,
        PROMPT_STATUS_FAILED,
    }
)


PUBLICATION_ERROR_TIMEOUT = "timeout"
PUBLICATION_ERROR_LOCK_BUSY = "lock_busy"
PUBLICATION_ERROR_INDEX_LOCK = "index_lock"
PUBLICATION_ERROR_UNSTAGED_CHANGES = "unstaged_changes"
PUBLICATION_ERROR_REBASE_CONFLICT = "rebase_conflict"
PUBLICATION_ERROR_MANIFEST_MISMATCH = "manifest_mismatch"
PUBLICATION_ERROR_UNKNOWN = "unknown"
PUBLICATION_ERROR_OTHER = "other"

PUBLICATION_FAILURE_SCOPE_REPOSITORY = "repository"
PUBLICATION_FAILURE_SCOPE_HOOD = "hood"
PUBLICATION_FAILURE_SCOPE_UNKNOWN = "unknown"

PUBLICATION_LIFECYCLE_ACTIVE = "active"
PUBLICATION_LIFECYCLE_QUARANTINED = "quarantined"
PUBLICATION_LIFECYCLE_RETIRED = "retired"

_ERROR_CLASSES = frozenset(
    {
        PUBLICATION_ERROR_TIMEOUT,
        PUBLICATION_ERROR_LOCK_BUSY,
        PUBLICATION_ERROR_INDEX_LOCK,
        PUBLICATION_ERROR_UNSTAGED_CHANGES,
        PUBLICATION_ERROR_REBASE_CONFLICT,
        PUBLICATION_ERROR_MANIFEST_MISMATCH,
        PUBLICATION_ERROR_UNKNOWN,
        PUBLICATION_ERROR_OTHER,
    }
)
_FAILURE_SCOPES = frozenset(
    {
        PUBLICATION_FAILURE_SCOPE_REPOSITORY,
        PUBLICATION_FAILURE_SCOPE_HOOD,
        PUBLICATION_FAILURE_SCOPE_UNKNOWN,
    }
)
_LIFECYCLES = frozenset(
    {
        PUBLICATION_LIFECYCLE_ACTIVE,
        PUBLICATION_LIFECYCLE_QUARANTINED,
        PUBLICATION_LIFECYCLE_RETIRED,
    }
)


@dataclass(frozen=True)
class PublicationRetrySelected:
    global_agent: str
    primary_revision: str
    prior_class: str
    prior_failure: str
    error_class: str = PUBLICATION_ERROR_UNKNOWN

    @property
    def logical_key(self) -> tuple[str, str]:
        return self.global_agent, self.primary_revision


@dataclass(frozen=True)
class PublicationFailureCharge:
    global_agent: str
    primary_revision: str
    attempts: int
    increment_attempts: bool
    quarantine: bool
    retire: bool
    terminal_reason: str | None = None

    @property
    def logical_key(self) -> tuple[str, str]:
        return self.global_agent, self.primary_revision


@dataclass(frozen=True)
class PublicationFailureAccounting:
    schema_version: int
    scope: str
    charge: bool
    error_class: str
    charges: tuple[PublicationFailureCharge, ...]


@dataclass(frozen=True)
class PublicationDrainSelection:
    schema_version: int
    active: tuple[PublicationRetrySelected, ...]
    revive: tuple[PublicationRetrySelected, ...]


@dataclass(frozen=True)
class PublicationCompletionDecision:
    schema_version: int
    kind: str
    required_page: str
    fulfilled: bool
    reason: str


@dataclass(frozen=True)
class DeferredPromptDecision:
    schema_version: int
    status: str
    blocks_acknowledgment: bool
    reason: str


def classify_publication_error(error: str | None) -> str:
    """Return the stable failure class for one publication error message."""

    binding = require_rust_binding("classify_publication_error")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "error": error,
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict error class")
    error_class = require_str_field(raw, "error_class")
    if error_class not in _ERROR_CLASSES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown publication error class: {error_class}"
        )
    return error_class


def select_publication_retries(
    rows: Sequence[Mapping[str, Any]],
    *,
    retry_retired: bool,
    retry_quarantined: bool,
    limit: int | None = None,
    error_classes: Sequence[str] | None = None,
) -> tuple[PublicationRetrySelected, ...]:
    """Return the terminal rows one explicit retry should revive."""

    binding = require_rust_binding("select_publication_retries")
    payload: dict[str, Any] = {
        "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
        "retry_retired": bool(retry_retired),
        "retry_quarantined": bool(retry_quarantined),
        "rows": [dict(row) for row in rows],
    }
    if limit is not None:
        payload["limit"] = limit
    if error_classes:
        payload["error_classes"] = list(error_classes)
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict retry selection")
    selected = raw.get("selected")
    if not isinstance(selected, list):
        raise RuntimeError("sase_core_rs retry selection is missing selected")
    return tuple(
        _parse_retry_selected(item, f"sase_core_rs retry selected[{index}]")
        for index, item in enumerate(selected)
    )


def decide_publication_failure_accounting(
    *,
    error: str,
    scope: str | None = None,
    attempted_keys: Sequence[Mapping[str, Any] | tuple[str, str]] = (),
    rows: Sequence[Mapping[str, Any]] = (),
    format_error: bool = False,
    quarantine_threshold: int | None = None,
) -> PublicationFailureAccounting:
    """Decide whether a failure may charge the host-supplied attempted keys."""

    binding = require_rust_binding("decide_publication_failure_accounting")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "scope": scope,
            "error": error,
            "format_error": bool(format_error),
            "attempted_keys": [_logical_key_payload(key) for key in attempted_keys],
            "rows": [dict(row) for row in rows],
            "quarantine_threshold": quarantine_threshold,
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict failure accounting")
    decision = PublicationFailureAccounting(
        schema_version=require_int(raw, "schema_version"),
        scope=require_str_field(raw, "scope"),
        charge=require_bool(raw, "charge"),
        error_class=require_str_field(raw, "error_class"),
        charges=_parse_failure_charges(raw.get("charges")),
    )
    if decision.schema_version != PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs publication recovery wire is stale: {decision.schema_version}"
        )
    if decision.scope not in _FAILURE_SCOPES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown failure scope: {decision.scope}"
        )
    if decision.error_class not in _ERROR_CLASSES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown publication error class: {decision.error_class}"
        )
    return decision


def select_publication_drain(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    preferred_key: tuple[str, str] | Mapping[str, Any] | None = None,
    retry_retired: bool = False,
    retry_quarantined: bool = False,
    error_classes: Sequence[str] | None = None,
) -> PublicationDrainSelection:
    """Select at most *limit* distinct logical requests for one drain."""

    binding = require_rust_binding("select_publication_drain")
    payload: dict[str, Any] = {
        "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
        "limit": limit,
        "retry_retired": bool(retry_retired),
        "retry_quarantined": bool(retry_quarantined),
        "rows": [dict(row) for row in rows],
    }
    if preferred_key is not None:
        payload["preferred_key"] = _logical_key_payload(preferred_key)
    if error_classes:
        payload["error_classes"] = list(error_classes)
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict drain selection")
    selection = PublicationDrainSelection(
        schema_version=require_int(raw, "schema_version"),
        active=_parse_selected_list(raw.get("active"), "active"),
        revive=_parse_selected_list(raw.get("revive"), "revive"),
    )
    if selection.schema_version != PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs publication recovery wire is stale: {selection.schema_version}"
        )
    return selection


def decide_publication_request_completion(
    *,
    global_agent: str,
    local_agent: str,
    primary_revision: str,
    pages: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]] = (),
    containers: Sequence[Mapping[str, Any]] = (),
    scope: str = "",
) -> PublicationCompletionDecision:
    """Decide whether a request's canonical page and revision are present."""

    binding = require_rust_binding("decide_publication_request_completion")
    request_identity: dict[str, Any] = {
        "global_agent": global_agent,
        "local_agent": local_agent,
        "primary_revision": primary_revision,
    }
    if scope:
        request_identity["scope"] = scope
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "request": request_identity,
            "pages": [dict(page) for page in pages],
            "runs": [dict(run) for run in runs],
            "containers": [dict(container) for container in containers],
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict completion decision")
    decision = PublicationCompletionDecision(
        schema_version=require_int(raw, "schema_version"),
        kind=require_str_field(raw, "kind"),
        required_page=require_str_field(raw, "required_page"),
        fulfilled=require_bool(raw, "fulfilled"),
        reason=require_str_field(raw, "reason"),
    )
    if decision.schema_version != PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs publication recovery wire is stale: {decision.schema_version}"
        )
    if decision.kind not in _KINDS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown publication kind: {decision.kind}"
        )
    return decision


def classify_deferred_prompt_obligation(
    *,
    restore_wrote: bool,
    restore_error: str | None,
    local_source_present: bool,
    archive_present: bool,
    prompt_file_in_snapshot: bool | None,
) -> DeferredPromptDecision:
    """Classify one deferred prompt as restored, archived, n/a, unavailable, or failed."""

    binding = require_rust_binding("classify_deferred_prompt_obligation")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "restore_wrote": bool(restore_wrote),
            "restore_error": restore_error,
            "local_source_present": bool(local_source_present),
            "archive_present": bool(archive_present),
            "prompt_file_in_snapshot": prompt_file_in_snapshot,
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict prompt decision")
    decision = DeferredPromptDecision(
        schema_version=require_int(raw, "schema_version"),
        status=require_str_field(raw, "status"),
        blocks_acknowledgment=require_bool(raw, "blocks_acknowledgment"),
        reason=require_str_field(raw, "reason"),
    )
    if decision.schema_version != PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs publication recovery wire is stale: {decision.schema_version}"
        )
    if decision.status not in _PROMPT_STATUSES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown prompt status: {decision.status}"
        )
    return decision


def _parse_retry_selected(item: object, label: str) -> PublicationRetrySelected:
    if not isinstance(item, dict):
        raise RuntimeError(f"{label} is not dict")
    selected = PublicationRetrySelected(
        global_agent=require_str_field(item, "global_agent"),
        primary_revision=require_str_field(item, "primary_revision"),
        prior_class=require_str_field(item, "prior_class"),
        prior_failure=require_str_field(item, "prior_failure"),
        error_class=require_str_field(item, "error_class"),
    )
    if selected.prior_class not in _LIFECYCLES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown publication lifecycle: {selected.prior_class}"
        )
    if selected.error_class not in _ERROR_CLASSES:
        raise RuntimeError(
            f"sase_core_rs returned an unknown publication error class: {selected.error_class}"
        )
    return selected


def _parse_selected_list(
    raw: object,
    field: str,
) -> tuple[PublicationRetrySelected, ...]:
    if not isinstance(raw, list):
        raise RuntimeError(f"sase_core_rs drain selection is missing {field}")
    return tuple(
        _parse_retry_selected(item, f"sase_core_rs drain {field}[{index}]")
        for index, item in enumerate(raw)
    )


def _parse_failure_charges(raw: object) -> tuple[PublicationFailureCharge, ...]:
    if not isinstance(raw, list):
        raise RuntimeError("sase_core_rs failure accounting is missing charges")
    charges: list[PublicationFailureCharge] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"sase_core_rs failure charge[{index}] is not dict")
        terminal_reason = item.get("terminal_reason")
        if terminal_reason is not None and not isinstance(terminal_reason, str):
            raise RuntimeError(
                f"sase_core_rs failure charge[{index}] terminal_reason is not str"
            )
        charges.append(
            PublicationFailureCharge(
                global_agent=require_str_field(item, "global_agent"),
                primary_revision=require_str_field(item, "primary_revision"),
                attempts=require_int(item, "attempts"),
                increment_attempts=require_bool(item, "increment_attempts"),
                quarantine=require_bool(item, "quarantine"),
                retire=require_bool(item, "retire"),
                terminal_reason=terminal_reason,
            )
        )
    return tuple(charges)


def _logical_key_payload(
    key: Mapping[str, Any] | tuple[str, str],
) -> dict[str, str]:
    if isinstance(key, tuple):
        global_agent, primary_revision = key
        return {
            "global_agent": global_agent,
            "primary_revision": primary_revision,
        }
    return {
        "global_agent": str(key["global_agent"]),
        "primary_revision": str(key["primary_revision"]),
    }
