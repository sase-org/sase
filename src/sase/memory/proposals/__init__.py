"""Proposal storage for ``sase memory write``."""

from __future__ import annotations

import getpass
import socket

from sase.memory.read_log import (
    AgentIdentity,
    AgentIdentityError,
    require_agent_identity,
)
from sase.memory.proposals.identity import (
    proposal_author_from_agent,
    require_proposal_author,
    require_proposal_reviewer,
)
from sase.memory.proposals.ledger import (
    memory_proposal_event_to_dict,
    memory_proposal_ledger_event_to_dict,
    memory_proposal_state_to_dict,
    read_memory_proposal_events,
    read_memory_proposals,
    reduce_memory_proposal_events,
    resolve_memory_proposal_id,
)
from sase.memory.proposals.models import (
    MEMORY_PROPOSAL_BODY_MAX_BYTES,
    MEMORY_PROPOSAL_BODY_WARN_BYTES,
    MEMORY_PROPOSAL_SCHEMA_VERSION,
    EvidenceKind,
    EvidenceRecord,
    MemoryProposalAuthorError,
    MemoryProposalBodyError,
    MemoryProposalError,
    MemoryProposalEvent,
    MemoryProposalEvidenceError,
    MemoryProposalLedgerEvent,
    MemoryProposalLookupError,
    MemoryProposalReviewEvent,
    MemoryProposalReviewError,
    MemoryProposalReviewResult,
    MemoryProposalState,
    MemoryProposalTargetError,
    MemoryProposalWriteResult,
    ProposalAuthor,
    ProposalEventType,
    ProposalReviewer,
    ProposalStatus,
    ProposalWarning,
    ReviewProposalEventType,
)
from sase.memory.proposals.paths import (
    memory_proposal_ledger_path,
    memory_proposal_lock_path,
)
from sase.memory.proposals.review import (
    approve_memory_proposal,
    prepare_memory_proposal_edit,
    reject_memory_proposal,
)
from sase.memory.proposals.validation import (
    build_memory_proposal_warnings,
    generate_memory_proposal_id,
    parse_memory_proposal_evidence,
    validate_memory_proposal_target,
)
from sase.memory.proposals.write import create_memory_proposal

_COMPAT_IMPORTS = (
    getpass,
    socket,
    AgentIdentity,
    AgentIdentityError,
    require_agent_identity,
)

__all__ = [
    "MEMORY_PROPOSAL_BODY_MAX_BYTES",
    "MEMORY_PROPOSAL_BODY_WARN_BYTES",
    "MEMORY_PROPOSAL_SCHEMA_VERSION",
    "AgentIdentity",
    "AgentIdentityError",
    "EvidenceKind",
    "EvidenceRecord",
    "MemoryProposalAuthorError",
    "MemoryProposalBodyError",
    "MemoryProposalError",
    "MemoryProposalEvent",
    "MemoryProposalEvidenceError",
    "MemoryProposalLedgerEvent",
    "MemoryProposalLookupError",
    "MemoryProposalReviewEvent",
    "MemoryProposalReviewError",
    "MemoryProposalReviewResult",
    "MemoryProposalState",
    "MemoryProposalTargetError",
    "MemoryProposalWriteResult",
    "ProposalAuthor",
    "ProposalEventType",
    "ProposalReviewer",
    "ProposalStatus",
    "ProposalWarning",
    "ReviewProposalEventType",
    "approve_memory_proposal",
    "build_memory_proposal_warnings",
    "create_memory_proposal",
    "generate_memory_proposal_id",
    "memory_proposal_event_to_dict",
    "memory_proposal_ledger_event_to_dict",
    "memory_proposal_ledger_path",
    "memory_proposal_lock_path",
    "memory_proposal_state_to_dict",
    "parse_memory_proposal_evidence",
    "prepare_memory_proposal_edit",
    "proposal_author_from_agent",
    "read_memory_proposal_events",
    "read_memory_proposals",
    "reduce_memory_proposal_events",
    "reject_memory_proposal",
    "require_proposal_author",
    "require_proposal_reviewer",
    "require_agent_identity",
    "resolve_memory_proposal_id",
    "validate_memory_proposal_target",
]
