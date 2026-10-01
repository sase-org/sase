"""Shared helpers for the split pager provider modules.

Public helpers live here because more than one new ``pager_provider_*``
module needs them. Single-use helpers stay private inside their sole
consumer.
"""

from __future__ import annotations

from typing import Any


def wire_subject_id(response: dict[str, Any], fallback: str) -> str:
    """Return the wire subject id, preferring the explicit subject record.

    The version response carries the canonical id either as a subject
    mapping (``{"id": ...}``) or as a top-level ``subject_id`` string;
    both beat the bare selector the caller resolved.
    """
    subject = response.get("subject", {})
    if isinstance(subject, dict) and subject.get("id"):
        return str(subject.get("id"))
    wire_id = response.get("subject_id")
    if isinstance(wire_id, str) and wire_id:
        return wire_id
    return fallback


def wire_history_path(response: dict[str, Any], fallback: str) -> str:
    """Return the canonical repo-relative path for a version response."""
    subject = response.get("subject", {})
    if isinstance(subject, dict):
        paths = subject.get("paths", ())
        if isinstance(paths, (list, tuple)) and paths and paths[0]:
            return str(paths[0])
    version = response.get("version", {})
    if isinstance(version, dict):
        for key in ("path", "source_path"):
            candidate = version.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return fallback


__all__ = ["wire_history_path", "wire_subject_id"]
