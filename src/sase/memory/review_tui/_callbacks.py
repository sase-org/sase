"""Callback defaults for memory proposal review actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.memory.cli_review import edit_memory_proposal_via_editor
from sase.memory.proposals import (
    MemoryProposalReviewResult,
    approve_memory_proposal,
    reject_memory_proposal,
)

type ApproveCallback = Callable[
    [str, str | None, str | Path | None], MemoryProposalReviewResult
]
type RejectCallback = Callable[[str, str], MemoryProposalReviewResult]
type EditCallback = Callable[[str, str | None], MemoryProposalReviewResult]


def default_approve(
    proposal_id: str,
    target: str | None,
    edited_file: str | Path | None,
) -> MemoryProposalReviewResult:
    return approve_memory_proposal(
        proposal_id,
        target=target,
        edited_file=edited_file,
    )


def default_reject(
    proposal_id: str,
    reason: str,
) -> MemoryProposalReviewResult:
    return reject_memory_proposal(proposal_id, reason=reason)


def default_edit(
    proposal_id: str,
    target: str | None,
) -> MemoryProposalReviewResult:
    return edit_memory_proposal_via_editor(proposal_id, target=target)
