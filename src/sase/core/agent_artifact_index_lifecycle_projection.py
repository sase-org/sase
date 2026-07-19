"""Dismissed-identity inputs for artifact-index lifecycle maintenance."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_artifact_index_lifecycle_common import (
    AgentIdentityLike,
    DismissedAgentsSignature,
    DismissedBundleIndexSignature,
    DismissedProjectionInputs,
)

log = logging.getLogger(__name__)


def build_authoritative_dismissed_agent_projection_inputs(
    dismissed: Iterable[AgentIdentityLike],
    dismissed_agents_signature: DismissedAgentsSignature,
    dismissed_bundle_index_signature: DismissedBundleIndexSignature,
) -> DismissedProjectionInputs:
    """Build projection inputs from an authoritative caller-supplied set.

    Skips the on-disk bundle scan that ``build_dismissed_agent_projection_inputs``
    performs, paying only the cost of converting the caller's identities.
    """
    identities = {_identity_to_wire(identity) for identity in dismissed}
    return DismissedProjectionInputs(
        identities=sorted(identities),
        dismissed_agents_signature=dismissed_agents_signature,
        dismissed_bundle_index_signature=dismissed_bundle_index_signature,
        skipped_bundle_rows=0,
    )


def build_dismissed_agent_projection_inputs(
    dismissed: Iterable[AgentIdentityLike] | None = None,
) -> DismissedProjectionInputs:
    """Build artifact-index dismissed projection rows from state and bundles."""

    from sase.ace.dismissed_agents import (
        dismissed_agents_file_signature,
        dismissed_bundle_index_signature,
        load_dismissed_agents,
        load_dismissed_bundle_identities,
        rebuild_dismissed_bundle_index,
        verify_dismissed_bundle_index,
    )

    dismissed_identities = (
        set(dismissed) if dismissed is not None else load_dismissed_agents()
    )

    skipped_bundle_rows = 0
    try:
        bundle_report = verify_dismissed_bundle_index()
        if not bool(bundle_report.get("ok", False)):
            _, skipped_bundle_rows = rebuild_dismissed_bundle_index()
    except (OSError, RuntimeError, ValueError):
        log.debug("dismissed bundle index verification failed", exc_info=True)

    identities = {_identity_to_wire(identity) for identity in dismissed_identities}
    for agent_type, cl_name, raw_suffix in load_dismissed_bundle_identities():
        identities.add(
            AgentCleanupIdentityWire(
                agent_type=agent_type,
                cl_name=cl_name,
                raw_suffix=raw_suffix,
            )
        )

    return DismissedProjectionInputs(
        identities=sorted(identities),
        dismissed_agents_signature=dismissed_agents_file_signature(),
        dismissed_bundle_index_signature=dismissed_bundle_index_signature(),
        skipped_bundle_rows=skipped_bundle_rows,
    )


def _identity_to_wire(identity: AgentIdentityLike) -> AgentCleanupIdentityWire:
    agent_type, cl_name, raw_suffix = identity
    return AgentCleanupIdentityWire(
        agent_type=str(getattr(agent_type, "value", agent_type)),
        cl_name=str(cl_name),
        raw_suffix=None if raw_suffix is None else str(raw_suffix),
    )
