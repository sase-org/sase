"""The one accessor that turns a bead into flag key, kind, and thresholds.

Every flag-domain reader goes through :func:`flag_fields` so no module parses
``task_type_fields`` itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import re

from sase.bead.model import Issue, IssueType

FLAG_TASK_TYPE = "flag"

_SNAKE_CASE_FLAG_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_RELEASE_CORE_PART_RE = re.compile(r"^[0-9]+$")
_RELEASE_SUFFIX_RE = re.compile(r"^[A-Za-z0-9.\-]+$")


@dataclass(frozen=True)
class FlagFields:
    """Key, kind, and both removal thresholds for one flag bead."""

    key: str
    kind: str
    remove_by_date: str
    remove_by_release: str

    def validate(self) -> None:
        if not _is_snake_case_flag_key(self.key):
            raise ValueError(
                f"bead flag key must be non-empty snake_case: {self.key!r}"
            )
        _parse_flag_remove_by_date(self.remove_by_date)
        if not _is_release_string(self.remove_by_release):
            raise ValueError(
                "bead flag remove_by_release must be a release string: "
                f"{self.remove_by_release!r}"
            )


def is_flag_task_bead(issue: Issue) -> bool:
    """Return whether *issue* is a task bead of type ``flag``."""
    return issue.issue_type == IssueType.TASK and issue.task_type == FLAG_TASK_TYPE


def is_flag_bead(issue: Issue) -> bool:
    """Return whether *issue* is a flag for surface grouping."""
    return is_flag_task_bead(issue)


def flag_fields(issue: Issue) -> FlagFields | None:
    """Return key, kind, and both thresholds for a flag bead, else ``None``.

    Missing or empty thresholds decode to ``None``, matching the former
    :func:`flag_from_dict` tolerance for unusable persisted payloads.
    """
    if not is_flag_task_bead(issue):
        return None
    return _fields_from_mapping(issue.task_type_fields)


def replace_flag_thresholds(
    fields: Mapping[str, str],
    *,
    remove_by_date: str,
    remove_by_release: str,
) -> dict[str, str]:
    """Return *fields* with the two data-role thresholds replaced."""
    updated = dict(fields)
    updated["remove_by_date"] = remove_by_date
    updated["remove_by_release"] = remove_by_release
    return updated


def _fields_from_mapping(raw: Mapping[str, object]) -> FlagFields | None:
    key = str(raw.get("key", "")).strip()
    remove_by_date = str(raw.get("remove_by_date", "")).strip()
    remove_by_release = str(raw.get("remove_by_release", "")).strip()
    if not key or not remove_by_date or not remove_by_release:
        return None
    kind = str(raw.get("kind", "")).strip()
    return FlagFields(
        key=key,
        kind=kind,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )


def _is_snake_case_flag_key(value: str) -> bool:
    return bool(_SNAKE_CASE_FLAG_KEY_RE.match(value))


def _parse_flag_remove_by_date(value: str) -> date:
    """Parse a flag removal date, requiring a calendar ``YYYY-MM-DD`` ISO date."""
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"bead flag remove_by_date must be an ISO date: {value!r} ({exc})"
        ) from exc


def _is_release_string(value: str) -> bool:
    """Return whether *value* is ``X.Y.Z`` with an optional ``-``/``+`` suffix."""
    split_at = next((i for i, ch in enumerate(value) if ch in "-+"), None)
    core, suffix = (
        (value, None) if split_at is None else (value[:split_at], value[split_at + 1 :])
    )
    parts = core.split(".")
    if len(parts) != 3 or not all(_RELEASE_CORE_PART_RE.match(part) for part in parts):
        return False
    if suffix is None:
        return True
    return bool(suffix) and bool(_RELEASE_SUFFIX_RE.match(suffix))


__all__ = [
    "FLAG_TASK_TYPE",
    "FlagFields",
    "flag_fields",
    "is_flag_bead",
    "is_flag_task_bead",
    "replace_flag_thresholds",
]
