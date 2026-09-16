"""Core-safe agent-tribe validation and persistence readers.

The canonical assignment store is ``~/.sase/agent_tribes.json``.  The old
``agent_tags.json`` shapes are accepted only when the canonical file does not
exist; callers that mutate assignments write the complete imported state to
the canonical store.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.core.paths import sase_home

RawAgentTribeIdentity = tuple[str, str, str | None]

TRIBE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

#: Reserved display identity for the untagged agent bucket.  It is a panel
#: label, never a real tribe assignment, so it can never be a wait target.
RESERVED_DEFAULT_TRIBE = "default"

#: Every pseudo-tribe that exists only as a display identity.
RESERVED_TRIBE_NAMES: frozenset[str] = frozenset({RESERVED_DEFAULT_TRIBE})

# Historical AXE automation agents are stored as the built-in ``chop`` tribe.
# Public surfaces now expose that same identity as ``job``.
LEGACY_JOB_TRIBE = "chop"
PUBLIC_JOB_TRIBE = "job"


class InvalidTribeError(ValueError):
    """Raised when an agent tribe name fails validation."""


def _tribe_binding(name: str) -> Any:
    return require_rust_binding(name)


def _tribe_value_error(exc: ValueError) -> InvalidTribeError:
    return InvalidTribeError(str(exc))


def is_reserved_tribe_name(tribe: str) -> bool:
    """Return whether *tribe* names a reserved display-only pseudo-tribe.

    Reserved names stay valid for :func:`validate_tribe_name` and
    :func:`parse_tribe_reference` — they are legitimate configuration and
    panel identities — but they must never be used as a wait or fork target.
    """
    return bool(_tribe_binding("is_reserved_tribe_name")(tribe))


def reserved_tribe_target_reason(tribe: str) -> str:
    """Return the shared explanation for rejecting a reserved tribe target."""
    return str(_tribe_binding("reserved_tribe_target_reason")(tribe))


def validate_tribe_name(tribe: str) -> str:
    """Return *tribe* when it matches the persisted tribe grammar."""
    if not isinstance(tribe, str):
        raise InvalidTribeError("tribe name must be a non-empty string")
    try:
        return str(_tribe_binding("validate_tribe_name")(tribe))
    except ValueError as exc:
        raise _tribe_value_error(exc) from exc


def canonicalize_public_tribe_name(tribe: str) -> str:
    """Return the stable stored tribe identity for a public tribe name."""
    try:
        return str(_tribe_binding("canonicalize_public_tribe_name")(tribe))
    except ValueError as exc:
        raise _tribe_value_error(exc) from exc


def public_tribe_name(tribe: str) -> str:
    """Return the public display spelling for a stored/effective tribe name."""
    return str(_tribe_binding("public_tribe_name")(tribe))


def parse_tribe_reference(value: str) -> str | None:
    """Return the validated bare tribe from ``@<tribe>``, else ``None``."""
    try:
        result = _tribe_binding("parse_tribe_reference")(value)
    except ValueError as exc:
        raise _tribe_value_error(exc) from exc
    return result if isinstance(result, str) else None


def canonical_agent_tribes_path() -> Path:
    """Return the canonical standalone tribe-assignment path."""
    return sase_home() / "agent_tribes.json"


def legacy_agent_tags_path() -> Path:
    """Return the legacy standalone tribe-assignment path."""
    return sase_home() / "agent_tags.json"


def _load_json_list(path: Path) -> list[Any] | None:
    try:
        with open(path, encoding="utf-8") as store_file:
            data = json.load(store_file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) else None


def _identity_from_record(record: dict[str, Any]) -> RawAgentTribeIdentity | None:
    identity_raw = record.get("id")
    if not isinstance(identity_raw, list) or len(identity_raw) != 3:
        return None
    agent_type, cl_name, raw_suffix = identity_raw
    if not isinstance(agent_type, str) or not isinstance(cl_name, str):
        return None
    if raw_suffix is not None and not isinstance(raw_suffix, str):
        return None
    return agent_type, cl_name, raw_suffix


def _valid_stored_tribe(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        validate_tribe_name(value)
    except InvalidTribeError:
        return None
    return value


def _load_canonical_agent_tribes(path: Path) -> dict[RawAgentTribeIdentity, str]:
    records = _load_json_list(path)
    if records is None:
        return {}
    result: dict[RawAgentTribeIdentity, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        identity = _identity_from_record(record)
        tribe = _valid_stored_tribe(record.get("tribe"))
        if identity is not None and tribe is not None:
            result[identity] = tribe
    return result


def _load_legacy_agent_tags(path: Path) -> dict[RawAgentTribeIdentity, str]:
    """Read the scalar ``tag`` and older list ``tags`` legacy shapes."""
    records = _load_json_list(path)
    if records is None:
        return {}
    result: dict[RawAgentTribeIdentity, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        identity = _identity_from_record(record)
        if identity is None:
            continue
        tribe = _valid_stored_tribe(record.get("tag"))
        if tribe is None:
            old_values = record.get("tags")
            if isinstance(old_values, list):
                tribe = next(
                    (
                        valid
                        for candidate in old_values
                        if (valid := _valid_stored_tribe(candidate)) is not None
                    ),
                    None,
                )
        if tribe is not None:
            result[identity] = tribe
    return result


def load_raw_agent_tribes(
    path: str | Path | None = None,
    *,
    legacy_path: str | Path | None = None,
) -> dict[RawAgentTribeIdentity, str]:
    """Load canonical assignments, falling back to the legacy store.

    The canonical file is authoritative whenever it exists, including when
    it is empty or malformed.  This prevents a cleared assignment from being
    resurrected by a stale legacy file.
    """
    canonical = Path(path) if path is not None else canonical_agent_tribes_path()
    legacy = Path(legacy_path) if legacy_path is not None else legacy_agent_tags_path()
    if canonical.exists():
        return _load_canonical_agent_tribes(canonical)
    return _load_legacy_agent_tags(legacy)


def canonicalize_agent_tribe_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Rewrite one mutable metadata record to the canonical tribe shape.

    A valid legacy ``tag`` value is retained as ``tribe`` only when the new
    key is absent.  The legacy key is always removed, including when the
    canonical value is explicitly empty or invalid.
    """
    had_tribe = "tribe" in data
    original_tribe = data.get("tribe")
    probe: dict[str, Any] = {}
    if had_tribe:
        probe["tribe"] = original_tribe if isinstance(original_tribe, str) else None
    if "tag" in data:
        tag = data.get("tag")
        probe["tag"] = tag if isinstance(tag, str) else None

    result = _tribe_binding("canonicalize_agent_tribe_metadata")(probe)
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned non-dict tribe metadata")
    data.pop("tag", None)
    result_tribe = result.get("tribe")
    if isinstance(result_tribe, str):
        data["tribe"] = result_tribe
    elif not had_tribe:
        data.pop("tribe", None)
    return data


def agent_tribe_display_key(
    stored_tribe: str,
    configured_keys: list[str] | tuple[str, ...],
) -> str:
    """Return the display config key for one stored tribe identity."""
    try:
        return str(
            _tribe_binding("agent_tribe_display_key")(
                stored_tribe,
                list(configured_keys),
            )
        )
    except ValueError as exc:
        raise _tribe_value_error(exc) from exc


def resolve_agent_tribe_display_config(
    layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Return source-aware display alias diagnostics for serialized layers."""
    result = _tribe_binding("resolve_agent_tribe_display_config")(
        {"layers": list(layers)}
    )
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned non-dict tribe display resolution")
    return result


__all__ = [
    "InvalidTribeError",
    "LEGACY_JOB_TRIBE",
    "PUBLIC_JOB_TRIBE",
    "RESERVED_DEFAULT_TRIBE",
    "RESERVED_TRIBE_NAMES",
    "RawAgentTribeIdentity",
    "TRIBE_NAME_RE",
    "agent_tribe_display_key",
    "canonicalize_agent_tribe_metadata",
    "canonicalize_public_tribe_name",
    "canonical_agent_tribes_path",
    "is_reserved_tribe_name",
    "legacy_agent_tags_path",
    "load_raw_agent_tribes",
    "parse_tribe_reference",
    "public_tribe_name",
    "reserved_tribe_target_reason",
    "resolve_agent_tribe_display_config",
    "validate_tribe_name",
]
