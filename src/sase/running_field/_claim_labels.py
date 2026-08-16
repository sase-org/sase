"""Reserved RUNNING-field claim labels.

The ``RUNNING`` field records two different kinds of work: agent runs, and
machine-owned operational leases taken by chops, bead-claim reconciliation,
and plan archiving so host work gets a writable checkout. Only the former are
agents.

Operational leases wrap their caller-supplied workflow identity in a reserved
``lease(<workflow>)`` label so any reader can tell the two apart from the claim
line alone — the same way ``workflow(<name>)`` already marks a workflow claim.
"""

from __future__ import annotations

#: Prefix of the reserved RUNNING-field workflow label for a machine-owned
#: operational workspace lease.
OPERATIONAL_LEASE_CLAIM_PREFIX = "lease("


def operational_lease_claim_workflow(workflow: str) -> str:
    """Return the reserved RUNNING-field label for an operational lease.

    Idempotent: an already-wrapped label is returned unchanged so a normalized
    label fed back in is never double-wrapped.

    Args:
        workflow: Caller-supplied workflow identity (e.g. ``chop:bead_claim_checks``).

    Returns:
        The ``lease(<workflow>)`` label written to the RUNNING field.
    """
    if is_operational_lease_claim_workflow(workflow):
        return workflow
    return f"{OPERATIONAL_LEASE_CLAIM_PREFIX}{workflow})"


def is_operational_lease_claim_workflow(workflow: str | None) -> bool:
    """Return whether *workflow* is a reserved operational-lease claim label.

    Args:
        workflow: RUNNING-field workflow column value, if any.

    Returns:
        True when the label is the reserved ``lease(...)`` form.
    """
    return bool(
        workflow
        and workflow.startswith(OPERATIONAL_LEASE_CLAIM_PREFIX)
        and workflow.endswith(")")
    )
