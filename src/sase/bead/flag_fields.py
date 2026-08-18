"""The one accessor that turns a bead into flag key, kind, and thresholds.

Every flag-domain reader goes through :func:`flag_fields` so no module parses
``task_type_fields`` itself. During the migration window a legacy ``flag``
issue-type bead is still readable: its :class:`~sase.bead.model.FlagRecord`
maps onto the same four values, with ``kind`` empty because the old record
never stored one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.bead.model import Issue, IssueType

FLAG_TASK_TYPE = "flag"


@dataclass(frozen=True)
class FlagFields:
    """Key, kind, and both removal thresholds for one flag bead."""

    key: str
    kind: str
    remove_by_date: str
    remove_by_release: str


def is_flag_task_bead(issue: Issue) -> bool:
    """Return whether *issue* is a task bead of type ``flag``."""
    return issue.issue_type == IssueType.TASK and issue.task_type == FLAG_TASK_TYPE


def flag_fields(issue: Issue) -> FlagFields | None:
    """Return key, kind, and both thresholds for a flag bead, else ``None``.

    Prefers a ``flag`` task bead's field map. Falls back to a legacy flag
    issue-type record so the coexistence window stays readable. Missing or
    empty thresholds decode to ``None``, matching :func:`flag_from_dict`'s
    tolerance for unusable persisted payloads.
    """
    if is_flag_task_bead(issue):
        return _fields_from_mapping(issue.task_type_fields)
    if issue.flag is None:
        return None
    return _fields_from_mapping(
        {
            "key": issue.flag.key,
            "remove_by_date": issue.flag.remove_by_date,
            "remove_by_release": issue.flag.remove_by_release,
        }
    )


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


__all__ = [
    "FLAG_TASK_TYPE",
    "FlagFields",
    "flag_fields",
    "is_flag_task_bead",
    "replace_flag_thresholds",
]
