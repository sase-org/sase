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


@dataclass(frozen=True)
class PublicationRetrySelected:
    global_agent: str
    primary_revision: str
    prior_class: str
    prior_failure: str

    @property
    def logical_key(self) -> tuple[str, str]:
        return self.global_agent, self.primary_revision


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


def select_publication_retries(
    rows: Sequence[Mapping[str, Any]],
    *,
    retry_retired: bool,
    retry_quarantined: bool,
) -> tuple[PublicationRetrySelected, ...]:
    """Return the terminal rows one explicit retry should revive."""

    binding = require_rust_binding("select_publication_retries")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "retry_retired": bool(retry_retired),
            "retry_quarantined": bool(retry_quarantined),
            "rows": [dict(row) for row in rows],
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict retry selection")
    selected = raw.get("selected")
    if not isinstance(selected, list):
        raise RuntimeError("sase_core_rs retry selection is missing selected")
    items: list[PublicationRetrySelected] = []
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            raise RuntimeError(f"sase_core_rs retry selected[{index}] is not dict")
        items.append(
            PublicationRetrySelected(
                global_agent=_require_str_field(item, "global_agent"),
                primary_revision=_require_str_field(item, "primary_revision"),
                prior_class=_require_str_field(item, "prior_class"),
                prior_failure=_require_str_field(item, "prior_failure"),
            )
        )
    return tuple(items)


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


__all__ = [
    "DeferredPromptDecision",
    "PROMPT_STATUS_ALREADY_ARCHIVED",
    "PROMPT_STATUS_FAILED",
    "PROMPT_STATUS_NOT_APPLICABLE",
    "PROMPT_STATUS_RESTORED",
    "PROMPT_STATUS_UNAVAILABLE",
    "PUBLICATION_KIND_RUN",
    "PUBLICATION_KIND_SESSION",
    "PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION",
    "PublicationCompletionDecision",
    "PublicationRetrySelected",
    "classify_deferred_prompt_obligation",
    "decide_publication_request_completion",
    "select_publication_retries",
]
