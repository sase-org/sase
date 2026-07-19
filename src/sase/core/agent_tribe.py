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

from sase.core.paths import sase_home

RawAgentTribeIdentity = tuple[str, str, str | None]

TRIBE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class InvalidTribeError(ValueError):
    """Raised when an agent tribe name fails validation."""


def validate_tribe_name(tribe: str) -> str:
    """Return *tribe* when it matches the persisted tribe grammar."""
    if not isinstance(tribe, str) or not tribe:
        raise InvalidTribeError("tribe name must be a non-empty string")
    if tribe.startswith("@"):
        raise InvalidTribeError(
            f"tribe name {tribe!r} must not start with '@' "
            "(the '@' is added on display only — drop it from the input)"
        )
    if not TRIBE_NAME_RE.fullmatch(tribe):
        raise InvalidTribeError(
            f"tribe name {tribe!r} must match ^[A-Za-z0-9_.-]+$ "
            "(letters, digits, underscore, dot, dash)"
        )
    return tribe


def parse_tribe_reference(value: str) -> str | None:
    """Return the validated bare tribe from ``@<tribe>``, else ``None``."""
    if not value.startswith("@"):
        return None
    return validate_tribe_name(value[1:])


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
    if not isinstance(value, str) or not TRIBE_NAME_RE.fullmatch(value):
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


# Temporary compatibility names for the runtime-cutover phase.  They route
# default reads through the canonical store; an explicit path remains a
# narrowly scoped legacy-reader entry point used by old callers and fixtures.
InvalidTagError = InvalidTribeError
RawAgentTagIdentity = RawAgentTribeIdentity
TAG_NAME_RE = TRIBE_NAME_RE


def validate_tag_name(tag: str) -> str:
    """Compatibility wrapper for :func:`validate_tribe_name`."""
    return validate_tribe_name(tag)


def load_raw_agent_tags(
    path: str | Path | None = None,
) -> dict[RawAgentTribeIdentity, str]:
    """Compatibility reader for callers not yet moved to tribe names."""
    if path is not None:
        return _load_legacy_agent_tags(Path(path))
    return load_raw_agent_tribes()


__all__ = [
    "InvalidTribeError",
    "RawAgentTribeIdentity",
    "TRIBE_NAME_RE",
    "canonical_agent_tribes_path",
    "legacy_agent_tags_path",
    "load_raw_agent_tribes",
    "parse_tribe_reference",
    "validate_tribe_name",
]
