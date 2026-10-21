"""Replay path, byte-divergence, hood-merge, and apply decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.core._agent_publication_recovery_shared import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    require_bool,
    require_int,
    require_str_field,
    require_str_tuple,
)
from sase.core.rust import require_rust_binding

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
        path = require_str_field(item, "path")
        class_name = require_str_field(item, "class")
        if class_name not in _REPLAY_PATH_CLASSES:
            raise RuntimeError(
                f"sase_core_rs returned an unknown replay path class: {class_name}"
            )
        entries.append((path, class_name))
    return ReplayPathClassification(
        schema_version=require_int(raw, "schema_version"),
        entries=tuple(entries),
        browsing=require_str_tuple(raw, "browsing"),
        owner_content=require_str_tuple(raw, "owner_content"),
        archive_object=require_str_tuple(raw, "archive_object"),
        unknown=require_str_tuple(raw, "unknown"),
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
    action = require_str_field(raw, "action")
    if action not in _REPLAY_BYTE_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay byte action: {action}"
        )
    return ReplayByteDivergenceDecision(
        schema_version=require_int(raw, "schema_version"),
        action=action,
        retained=require_bool(raw, "retained"),
        reason=require_str_field(raw, "reason"),
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
    action = require_str_field(raw, "action")
    if action not in _REPLAY_HOOD_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay hood action: {action}"
        )
    return ReplayHoodMergeDecision(
        schema_version=require_int(raw, "schema_version"),
        action=action,
        reason=require_str_field(raw, "reason"),
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
    action = require_str_field(raw, "action")
    if action not in _REPLAY_APPLY_ACTIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown replay apply action: {action}"
        )
    return ReplayApplyDecision(
        schema_version=require_int(raw, "schema_version"),
        action=action,
        reason=require_str_field(raw, "reason"),
    )
