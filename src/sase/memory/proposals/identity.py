"""Author and reviewer identity helpers for memory proposals."""

from __future__ import annotations

from collections.abc import Mapping
import getpass
import os
import socket

from sase.memory.proposals.models import (
    MemoryProposalAuthorError,
    MemoryProposalReviewError,
    ProposalAuthor,
    ProposalReviewer,
)
from sase.memory.read_log import (
    AgentIdentity,
    AgentIdentityError,
    discover_agent_identity,
    require_agent_identity,
)


def require_proposal_author(
    *,
    manual_author: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProposalAuthor:
    """Return the current proposal author or raise a write-specific error."""
    if manual_author is not None:
        name = manual_author.strip()
        if not name:
            raise MemoryProposalAuthorError("manual proposal author must not be empty")
        return ProposalAuthor(name=name, source="manual", artifacts_dir=None)

    try:
        identity = require_agent_identity(env)
    except AgentIdentityError as exc:
        raise MemoryProposalAuthorError(
            "memory writes require agent attribution; set SASE_AGENT_NAME, "
            "provide SASE_ARTIFACTS_DIR/agent_meta.json with a name, "
            "or pass --manual-author for tests and demos"
        ) from exc
    return proposal_author_from_agent(identity)


def proposal_author_from_agent(agent: AgentIdentity) -> ProposalAuthor:
    """Convert a read-log agent identity to a proposal author."""
    return ProposalAuthor(
        name=agent.name,
        source=agent.source,
        artifacts_dir=agent.artifacts_dir,
    )


def require_proposal_reviewer(
    *, env: Mapping[str, str] | None = None
) -> ProposalReviewer:
    """Return the current human reviewer or raise for agent environments."""
    environment = os.environ if env is None else env
    if (
        environment.get("SASE_AGENT")
        or discover_agent_identity(environment) is not None
    ):
        raise MemoryProposalReviewError(
            "memory proposal review must be performed by a human reviewer; "
            "agents cannot approve or reject proposals"
        )

    user = getpass.getuser().strip() or "unknown"
    hostname = socket.gethostname().strip() or "unknown"
    return ProposalReviewer(user=user, hostname=hostname)
