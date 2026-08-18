"""The one shared removal-urgency predicate for flag beads.

A flag is due only when *both* its date and release thresholds have passed
(see the epic plan's decision that dates alone are badly calibrated and
releases alone have no calendar meaning). Every surface that renders or acts
on a flag bead's urgency -- the reconciler, the CLI, the doctor, the lint, and
every renderer -- must derive it through :func:`flag_removal_due` rather than
recompute the comparison itself, so "due" cannot mean one thing in one place
and something else in another.

This is a pure function of its arguments: callers own the clock and the
current release string, so no test needs to freeze time globally and no
renderer can disagree with another about what "due" means.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

FlagRemovalState = Literal["live", "soon", "due"]


def flag_removal_due(
    remove_by_date: str, remove_by_release: str, *, today: date, release: str
) -> FlagRemovalState:
    """Return removal urgency for the two thresholds as of *today* and *release*.

    - ``"live"`` -- neither threshold has been reached.
    - ``"soon"`` -- exactly one threshold has been reached.
    - ``"due"`` -- both thresholds have been reached.
    """
    date_reached = today >= date.fromisoformat(remove_by_date)
    release_reached = _release_tuple(release) >= _release_tuple(remove_by_release)
    if date_reached and release_reached:
        return "due"
    if date_reached or release_reached:
        return "soon"
    return "live"


def _release_tuple(value: str) -> tuple[int, int, int]:
    """Return the ``(major, minor, patch)`` core, ignoring any suffix."""
    core = value.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = core.split(".")
    return (int(major), int(minor), int(patch))


__all__ = [
    "FlagRemovalState",
    "flag_removal_due",
]
