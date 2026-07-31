"""Typed Python facade for the Rust commit-subject contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

COMMIT_SUBJECT_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _CommitSubject:
    subject: str
    valid: bool
    exempt: bool
    commit_type: str | None
    scope: str | None
    breaking: bool
    description: str | None
    violation: str | None
    found_type: str | None


def default_commit_subject_types() -> tuple[str, ...]:
    """Return the shared default Conventional Commit type allowlist."""
    binding = require_rust_binding("default_commit_subject_types")
    raw = binding()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise TypeError("default_commit_subject_types returned a non-string list")
    return tuple(raw)


def parse_commit_subject(
    message: str,
    allowed_types: Sequence[str] | None = None,
) -> _CommitSubject:
    """Parse *message* through the shared Rust subject grammar."""
    binding = require_rust_binding("parse_commit_subject")
    effective_types = (
        default_commit_subject_types()
        if allowed_types is None
        else tuple(str(item) for item in allowed_types)
    )
    raw = binding(message, list(effective_types))
    if not isinstance(raw, dict):
        raise TypeError("parse_commit_subject returned a non-dict payload")
    schema_version = int(raw.get("schema_version", -1))
    if schema_version != COMMIT_SUBJECT_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported commit-subject wire schema version "
            f"{schema_version}; expected {COMMIT_SUBJECT_WIRE_SCHEMA_VERSION}"
        )
    return _CommitSubject(
        subject=str(raw.get("subject") or ""),
        valid=bool(raw.get("valid")),
        exempt=bool(raw.get("exempt")),
        commit_type=_optional_str(raw.get("commit_type")),
        scope=_optional_str(raw.get("scope")),
        breaking=bool(raw.get("breaking")),
        description=_optional_str(raw.get("description")),
        violation=_optional_str(raw.get("violation")),
        found_type=_optional_str(raw.get("found_type")),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "COMMIT_SUBJECT_WIRE_SCHEMA_VERSION",
    "default_commit_subject_types",
    "parse_commit_subject",
]
