"""Refuse agent-run ``sase bead open`` on beads that are not closed."""

from __future__ import annotations

import sys
from collections.abc import Callable

from sase.bead.model import Issue, Status


def _agent_open_refusal_message(issue_id: str, status_value: str) -> str:
    """Return the refusal text for an agent reopen of a non-closed bead."""
    return (
        f"`sase bead open` reopens a closed bead; `{issue_id}` is not closed "
        f"(status: {status_value}). To view a bead run "
        f"`sase bead read {issue_id} -r '<why>'`."
    )


def refuse_agent_open_of_non_closed(
    show: Callable[[str], Issue],
    issue_id: str,
) -> None:
    """Exit 2 when an agent runs ``sase bead open`` on a non-closed bead.

    Fires only when an agent identity is present and the target bead exists
    with a status other than closed. Humans are never refused, missing beads
    fall through to the normal not-found error, and closed beads reopen as
    before (the host-notice closed-bead launch flow).
    """
    from sase.bead.attribution import acting_agent_name

    if not acting_agent_name():
        return
    try:
        issue = show(issue_id)
    except KeyError:
        return
    if issue.status is Status.CLOSED:
        return
    print(
        f"Error: {_agent_open_refusal_message(issue_id, issue.status.value)}",
        file=sys.stderr,
    )
    sys.exit(2)
