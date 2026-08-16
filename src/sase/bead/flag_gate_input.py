"""The declared new-threshold input the FlagTriage Extend option collects.

An Extend decision needs two arguments -- the new remove-by date and the new
remove-by release -- so this mirrors :mod:`sase.bead.snooze_gate_input`: the
declaration is one ordinary pair of declared line inputs, and the value
reaches the option command on stdin, where the command (not the host)
resolves it. An unparsable date or malformed release string fails the command
and leaves the gate pending rather than the reviewer's answer.

The wake-time vocabulary is reused for the date field via
:mod:`sase.bead.snooze_time` so a reviewer can type a relative duration
(``90d``) or an absolute date/timestamp interchangeably with every other
deferral surface in this codebase.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.bead.snooze_time import ACCEPTED_SNOOZE_FORMS, SnoozeTimeError

FLAG_TRIAGE_UNTIL_FIELD_ID = "until"
FLAG_TRIAGE_RELEASE_FIELD_ID = "release"

_UNTIL_PLACEHOLDER = "e.g., 90d or 2026-12-01"
_UNTIL_HELP = f"the new remove-by date; {ACCEPTED_SNOOZE_FORMS}"
_RELEASE_PLACEHOLDER = "e.g., 0.17.0"
_RELEASE_HELP = "the new remove-by release, e.g. 0.17.0 or 0.17.0-rc1"


def flag_triage_extend_inputs() -> list[dict[str, Any]]:
    """Return the ``inputs`` declaration the Extend option carries.

    A pure function of nothing, because gate validation rebuilds the request
    spec from its payload and compares it byte for byte.
    """
    return [
        {
            "id": FLAG_TRIAGE_UNTIL_FIELD_ID,
            "label": "New remove-by date",
            "type": "line",
            "required": True,
            "placeholder": _UNTIL_PLACEHOLDER,
            "help": _UNTIL_HELP,
        },
        {
            "id": FLAG_TRIAGE_RELEASE_FIELD_ID,
            "label": "New remove-by release",
            "type": "line",
            "required": True,
            "placeholder": _RELEASE_PLACEHOLDER,
            "help": _RELEASE_HELP,
        },
    ]


def resolve_flag_triage_extend(raw_input: Mapping[str, Any]) -> tuple[str, str]:
    """Return the ``(remove_by_date, remove_by_release)`` one Extend input names.

    *until* is resolved through :func:`sase.bead.snooze_time.parse_snooze_request`
    so every deferral surface in this codebase accepts the same vocabulary; only
    its date part is kept, since a flag's removal threshold is a calendar date
    rather than an instant. *release* is validated by constructing a
    :class:`~sase.bead.model.FlagRecord` and calling ``.validate()``, so the
    release-string rule cannot drift from the store's.

    Raises:
        SnoozeTimeError: If *until* is missing, of the wrong type, or names no
            usable date.
        ValueError: If *release* is missing, of the wrong type, or is not a
            valid release string.
    """
    from sase.bead.model import FlagRecord
    from sase.bead.snooze_time import parse_snooze_request

    until = raw_input.get(FLAG_TRIAGE_UNTIL_FIELD_ID)
    if not isinstance(until, str) or not until.strip():
        raise SnoozeTimeError(
            f"{FLAG_TRIAGE_UNTIL_FIELD_ID} must be a string; {ACCEPTED_SNOOZE_FORMS}"
        )
    request = parse_snooze_request(until.strip())
    remove_by_date = request.until[:10]

    release = raw_input.get(FLAG_TRIAGE_RELEASE_FIELD_ID)
    if not isinstance(release, str) or not release.strip():
        raise ValueError(
            f"{FLAG_TRIAGE_RELEASE_FIELD_ID} must be a non-empty release string"
        )
    record = FlagRecord(
        key="placeholder",
        remove_by_date=remove_by_date,
        remove_by_release=release.strip(),
    )
    record.validate()
    return remove_by_date, record.remove_by_release


__all__ = [
    "FLAG_TRIAGE_RELEASE_FIELD_ID",
    "FLAG_TRIAGE_UNTIL_FIELD_ID",
    "flag_triage_extend_inputs",
    "resolve_flag_triage_extend",
]
