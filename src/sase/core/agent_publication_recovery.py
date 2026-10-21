"""Rust-backed policy facade for agent publication recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION = 1

PUBLICATION_KIND_RUN = "run"
PUBLICATION_KIND_SESSION = "session"

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

REPLAY_PATH_BROWSING = "browsing"
REPLAY_PATH_OWNER_CONTENT = "owner_content"
REPLAY_PATH_ARCHIVE_OBJECT = "archive_object"
REPLAY_PATH_UNKNOWN = "unknown"

REPLAY_BYTES_KEEP_CURRENT = "keep_current"
REPLAY_BYTES_KEEP_PREVIOUS = "keep_previous"
REPLAY_BYTES_REFUSE = "refuse"

REPLAY_APPLY_ACTION_REPORT = "report"
REPLAY_APPLY_ACTION_APPLY = "apply"
REPLAY_APPLY_ACTION_REFUSE = "refuse"
REPLAY_APPLY_ACTION_ALREADY_COMPLETE = "already_complete"

REPLAY_HOOD_ACTION_MERGE = "merge"
REPLAY_HOOD_ACTION_REFUSE = "refuse"

_REPLAY_PATH_CLASSES = frozenset(
    {
        REPLAY_PATH_BROWSING,
        REPLAY_PATH_OWNER_CONTENT,
        REPLAY_PATH_ARCHIVE_OBJECT,
        REPLAY_PATH_UNKNOWN,
    }
)
_REPLAY_BYTE_ACTIONS = frozenset(
    {
        REPLAY_BYTES_KEEP_CURRENT,
        REPLAY_BYTES_KEEP_PREVIOUS,
        REPLAY_BYTES_REFUSE,
    }
)
_REPLAY_APPLY_ACTIONS = frozenset(
    {
        REPLAY_APPLY_ACTION_REPORT,
        REPLAY_APPLY_ACTION_APPLY,
        REPLAY_APPLY_ACTION_REFUSE,
        REPLAY_APPLY_ACTION_ALREADY_COMPLETE,
    }
)
_REPLAY_HOOD_ACTIONS = frozenset({REPLAY_HOOD_ACTION_MERGE, REPLAY_HOOD_ACTION_REFUSE})

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


@dataclass(frozen=True)
class ReplayPathClassification:
    schema_version: int
    entries: tuple[tuple[str, str], ...]
    browsing: tuple[str, ...]
    owner_content: tuple[str, ...]
    archive_object: tuple[str, ...]
    unknown: tuple[str, ...]


@dataclass(frozen=True)
class ReplayByteDivergenceDecision:
    schema_version: int
    action: str
    retained: bool
    reason: str


@dataclass(frozen=True)
class ReplayHoodMergeDecision:
    schema_version: int
    action: str
    reason: str


@dataclass(frozen=True)
class ReplayApplyDecision:
    schema_version: int
    action: str
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
    error_class = _require_str_field(raw, "error_class")
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
        schema_version=_require_int(raw, "schema_version"),
        scope=_require_str_field(raw, "scope"),
        charge=_require_bool(raw, "charge"),
        error_class=_require_str_field(raw, "error_class"),
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
        schema_version=_require_int(raw, "schema_version"),
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
) -> PublicationCompletionDecision:
    """Decide whether a request's canonical page and revision are present."""

    binding = require_rust_binding("decide_publication_request_completion")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "request": {
                "global_agent": global_agent,
                "local_agent": local_agent,
                "primary_revision": primary_revision,
            },
            "pages": [dict(page) for page in pages],
            "runs": [dict(run) for run in runs],
            "containers": [dict(container) for container in containers],
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict completion decision")
    decision = PublicationCompletionDecision(
        schema_version=_require_int(raw, "schema_version"),
        kind=_require_str_field(raw, "kind"),
        required_page=_require_str_field(raw, "required_page"),
        fulfilled=_require_bool(raw, "fulfilled"),
        reason=_require_str_field(raw, "reason"),
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
        schema_version=_require_int(raw, "schema_version"),
        status=_require_str_field(raw, "status"),
        blocks_acknowledgment=_require_bool(raw, "blocks_acknowledgment"),
        reason=_require_str_field(raw, "reason"),
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
        global_agent=_require_str_field(item, "global_agent"),
        primary_revision=_require_str_field(item, "primary_revision"),
        prior_class=_require_str_field(item, "prior_class"),
        prior_failure=_require_str_field(item, "prior_failure"),
        error_class=_require_str_field(item, "error_class"),
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
                global_agent=_require_str_field(item, "global_agent"),
                primary_revision=_require_str_field(item, "primary_revision"),
                attempts=_require_int(item, "attempts"),
                increment_attempts=_require_bool(item, "increment_attempts"),
                quarantine=_require_bool(item, "quarantine"),
                retire=_require_bool(item, "retire"),
                terminal_reason=terminal_reason,
            )
        )
    return tuple(charges)


def classify_replay_paths(
    paths: Sequence[str],
) -> ReplayPathClassification:
    """Classify sidecar paths through ``sase_core_rs``."""

    binding = require_rust_binding("classify_replay_paths")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "paths": list(paths),
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict replay path class")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise RuntimeError("sase_core_rs replay path class is missing entries")
    entries: list[tuple[str, str]] = []
    for index, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"sase_core_rs replay path entry[{index}] is not dict")
        path = _require_str_field(item, "path")
        class_name = _require_str_field(item, "class")
        if class_name not in _REPLAY_PATH_CLASSES:
            raise RuntimeError(
                f"sase_core_rs returned an unknown replay path class: {class_name}"
            )
        entries.append((path, class_name))
    return ReplayPathClassification(
        schema_version=_require_int(raw, "schema_version"),
        entries=tuple(entries),
        browsing=_require_str_tuple(raw, "browsing"),
        owner_content=_require_str_tuple(raw, "owner_content"),
        archive_object=_require_str_tuple(raw, "archive_object"),
        unknown=_require_str_tuple(raw, "unknown"),
    )


def decide_replay_byte_divergence(
    current: bytes,
    previous: bytes,
) -> ReplayByteDivergenceDecision:
    """Decide whether same-run bytes are a lossless prefix or must refuse."""

    binding = require_rust_binding("decide_replay_byte_divergence")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "current_hex": current.hex(),
            "previous_hex": previous.hex(),
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict replay byte decision")
    action = _require_str_field(raw, "action")
    if action not in _REPLAY_BYTE_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay byte action: {action}"
        )
    return ReplayByteDivergenceDecision(
        schema_version=_require_int(raw, "schema_version"),
        action=action,
        retained=_require_bool(raw, "retained"),
        reason=_require_str_field(raw, "reason"),
    )


def decide_replay_hood_merge(
    *,
    local_owner_username: str,
    local_owner_machine: str,
    local_hood: str,
    upstream_owner_username: str,
    upstream_owner_machine: str,
    upstream_hood: str,
) -> ReplayHoodMergeDecision:
    """Decide whether a same-owner hood may merge through snapshot preservation."""

    binding = require_rust_binding("decide_replay_hood_merge")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "local_owner_username": local_owner_username,
            "local_owner_machine": local_owner_machine,
            "local_hood": local_hood,
            "upstream_owner_username": upstream_owner_username,
            "upstream_owner_machine": upstream_owner_machine,
            "upstream_hood": upstream_hood,
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict replay hood decision")
    action = _require_str_field(raw, "action")
    if action not in _REPLAY_HOOD_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay hood action: {action}"
        )
    return ReplayHoodMergeDecision(
        schema_version=_require_int(raw, "schema_version"),
        action=action,
        reason=_require_str_field(raw, "reason"),
    )


def decide_replay_apply(
    *,
    apply: bool,
    observed_head: str,
    expected_head: str,
    backup_complete: bool,
    backup_verified: bool,
    unreconcilable: bool,
    already_complete: bool,
    mutation_started: bool,
) -> ReplayApplyDecision:
    """Admit, refuse, or report a stale-replay apply against backup and HEAD facts."""

    binding = require_rust_binding("decide_replay_apply")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "apply": bool(apply),
            "observed_head": observed_head,
            "expected_head": expected_head,
            "backup_complete": bool(backup_complete),
            "backup_verified": bool(backup_verified),
            "unreconcilable": bool(unreconcilable),
            "already_complete": bool(already_complete),
            "mutation_started": bool(mutation_started),
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict replay apply decision")
    action = _require_str_field(raw, "action")
    if action not in _REPLAY_APPLY_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay apply action: {action}"
        )
    return ReplayApplyDecision(
        schema_version=_require_int(raw, "schema_version"),
        action=action,
        reason=_require_str_field(raw, "reason"),
    )


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


def _require_str_field(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not str"
        )
    return value


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not int"
        )
    return value


def _require_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw[key]
    if not isinstance(value, bool):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not bool"
        )
    return value


def _require_str_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not list[str]"
        )
    return tuple(value)


__all__ = [
    "DeferredPromptDecision",
    "PROMPT_STATUS_ALREADY_ARCHIVED",
    "PROMPT_STATUS_FAILED",
    "PROMPT_STATUS_NOT_APPLICABLE",
    "PROMPT_STATUS_RESTORED",
    "PROMPT_STATUS_UNAVAILABLE",
    "PUBLICATION_ERROR_INDEX_LOCK",
    "PUBLICATION_ERROR_LOCK_BUSY",
    "PUBLICATION_ERROR_MANIFEST_MISMATCH",
    "PUBLICATION_ERROR_OTHER",
    "PUBLICATION_ERROR_REBASE_CONFLICT",
    "PUBLICATION_ERROR_TIMEOUT",
    "PUBLICATION_ERROR_UNKNOWN",
    "PUBLICATION_ERROR_UNSTAGED_CHANGES",
    "PUBLICATION_FAILURE_SCOPE_HOOD",
    "PUBLICATION_FAILURE_SCOPE_REPOSITORY",
    "PUBLICATION_FAILURE_SCOPE_UNKNOWN",
    "PUBLICATION_KIND_RUN",
    "PUBLICATION_KIND_SESSION",
    "PUBLICATION_LIFECYCLE_ACTIVE",
    "PUBLICATION_LIFECYCLE_QUARANTINED",
    "PUBLICATION_LIFECYCLE_RETIRED",
    "PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION",
    "PublicationCompletionDecision",
    "PublicationDrainSelection",
    "PublicationFailureAccounting",
    "PublicationFailureCharge",
    "PublicationRetrySelected",
    "REPLAY_APPLY_ACTION_ALREADY_COMPLETE",
    "REPLAY_APPLY_ACTION_APPLY",
    "REPLAY_APPLY_ACTION_REFUSE",
    "REPLAY_APPLY_ACTION_REPORT",
    "REPLAY_BYTES_KEEP_CURRENT",
    "REPLAY_BYTES_KEEP_PREVIOUS",
    "REPLAY_BYTES_REFUSE",
    "REPLAY_HOOD_ACTION_MERGE",
    "REPLAY_HOOD_ACTION_REFUSE",
    "REPLAY_PATH_ARCHIVE_OBJECT",
    "REPLAY_PATH_BROWSING",
    "REPLAY_PATH_OWNER_CONTENT",
    "REPLAY_PATH_UNKNOWN",
    "ReplayApplyDecision",
    "ReplayByteDivergenceDecision",
    "ReplayHoodMergeDecision",
    "ReplayPathClassification",
    "classify_deferred_prompt_obligation",
    "classify_publication_error",
    "classify_replay_paths",
    "decide_publication_failure_accounting",
    "decide_publication_request_completion",
    "decide_replay_apply",
    "decide_replay_byte_divergence",
    "decide_replay_hood_merge",
    "select_publication_drain",
    "select_publication_retries",
]
