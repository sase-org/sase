"""Shared plan-approval choice registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

type PlanApprovalChoiceId = Literal[
    "approve",
    "run",
    "tale",
    "epic",
    "commit",
    "reject",
    "feedback",
]
type PlanApprovalModalChoice = Literal["approve", "tale", "epic"]
type PlanApprovalCliKind = Literal[
    "approve",
    "commit",
    "epic",
    "tale",
]


class PlanApprovalProtocolFields(NamedTuple):
    """Runner-facing response fields for an explicit approval choice."""

    action: str
    commit_plan: bool
    run_coder: bool


@dataclass(frozen=True)
class _PlanApprovalChoiceRecord:
    """Registered plan approval choice metadata."""

    id: PlanApprovalChoiceId
    display_label: str
    response_message: str
    protocol: PlanApprovalProtocolFields | None = None
    custom_modal_key: str | None = None
    review_modal_key: str | None = None
    consequence_text: str = ""
    cli_kind_name: PlanApprovalCliKind | None = None
    archive_side_effect: bool = False
    auto_mode_eligible: bool = False
    persist_action: str | None = None
    status_label: str | None = None
    requires_feedback: bool = False
    allow_protocol_overrides: bool = False
    allow_coder_options: bool = False


PLAN_APPROVAL_CHOICE_RECORDS: tuple[_PlanApprovalChoiceRecord, ...] = (
    _PlanApprovalChoiceRecord(
        id="approve",
        display_label="Approve",
        response_message="Plan approved",
        protocol=PlanApprovalProtocolFields(
            action="approve",
            commit_plan=False,
            run_coder=True,
        ),
        custom_modal_key="a",
        review_modal_key="a",
        consequence_text="No SDD commit; run coder",
        cli_kind_name="approve",
        archive_side_effect=True,
        auto_mode_eligible=True,
        persist_action="approve",
        status_label="PLAN APPROVED",
        allow_protocol_overrides=True,
        allow_coder_options=True,
    ),
    _PlanApprovalChoiceRecord(
        id="run",
        display_label="Run",
        response_message="Running coder",
        protocol=PlanApprovalProtocolFields(
            action="approve",
            commit_plan=False,
            run_coder=True,
        ),
        consequence_text="No SDD commit; run coder",
        archive_side_effect=True,
        persist_action="approve",
        status_label="PLAN APPROVED",
        allow_coder_options=True,
    ),
    _PlanApprovalChoiceRecord(
        id="tale",
        display_label="Tale",
        response_message="Tale approved",
        protocol=PlanApprovalProtocolFields(
            action="approve",
            commit_plan=True,
            run_coder=True,
        ),
        custom_modal_key="t",
        review_modal_key="t",
        consequence_text="Commit to sdd/plans (tier: tale); run coder",
        cli_kind_name="tale",
        archive_side_effect=True,
        auto_mode_eligible=True,
        persist_action="tale",
        status_label="TALE APPROVED",
        allow_coder_options=True,
    ),
    _PlanApprovalChoiceRecord(
        id="epic",
        display_label="Epic",
        response_message="Epic approved",
        protocol=PlanApprovalProtocolFields(
            action="epic",
            commit_plan=True,
            run_coder=True,
        ),
        custom_modal_key="e",
        review_modal_key="E",
        consequence_text=(
            "Commit to sdd/plans (tier: epic); launch beads via `sase bead work` "
            "(background task)"
        ),
        cli_kind_name="epic",
        auto_mode_eligible=True,
        persist_action="epic",
        status_label="EPIC APPROVED",
        allow_coder_options=False,
    ),
    _PlanApprovalChoiceRecord(
        id="commit",
        display_label="Commit",
        response_message="Plan committed",
        protocol=PlanApprovalProtocolFields(
            action="approve",
            commit_plan=True,
            run_coder=False,
        ),
        cli_kind_name="commit",
        archive_side_effect=True,
        persist_action="commit",
        status_label="PLAN COMMITTED",
    ),
    _PlanApprovalChoiceRecord(
        id="reject",
        display_label="Reject",
        response_message="Plan rejected",
    ),
    _PlanApprovalChoiceRecord(
        id="feedback",
        display_label="Feedback",
        response_message="Feedback received",
        requires_feedback=True,
    ),
)

_CHOICES_BY_ID: dict[str, _PlanApprovalChoiceRecord] = {
    record.id: record for record in PLAN_APPROVAL_CHOICE_RECORDS
}

PLAN_APPROVAL_CHOICE_IDS: tuple[PlanApprovalChoiceId, ...] = tuple(
    record.id for record in PLAN_APPROVAL_CHOICE_RECORDS
)
PLAN_APPROVAL_MODAL_CHOICES: tuple[PlanApprovalModalChoice, ...] = (
    "approve",
    "tale",
    "epic",
)
PLAN_APPROVAL_CLI_KINDS: tuple[PlanApprovalCliKind, ...] = (
    "approve",
    "commit",
    "epic",
    "tale",
)
PLAN_APPROVAL_AUTO_MODE_CHOICES: tuple[PlanApprovalChoiceId, ...] = tuple(
    record.id for record in PLAN_APPROVAL_CHOICE_RECORDS if record.auto_mode_eligible
)
PLAN_APPROVAL_REMOTE_CHOICES: tuple[PlanApprovalChoiceId, ...] = (
    "approve",
    "run",
    "reject",
    "epic",
    "feedback",
)


def _plan_approval_choice(choice: str) -> _PlanApprovalChoiceRecord | None:
    """Return the registered record for a choice string, if supported."""
    return _CHOICES_BY_ID.get(choice)


def require_plan_approval_choice(choice: str) -> _PlanApprovalChoiceRecord:
    """Return a registered choice record or raise ``KeyError``."""
    return _CHOICES_BY_ID[choice]


def approval_protocol_for_choice(choice: str) -> PlanApprovalProtocolFields:
    """Return the runner response protocol for an approval choice."""
    record = require_plan_approval_choice(choice)
    if record.protocol is None:
        raise KeyError(choice)
    return record.protocol


def approval_choice_status_label(choice: str) -> str | None:
    """Return the immediate TUI status label for an approving choice."""
    record = _plan_approval_choice(choice)
    return None if record is None else record.status_label


def approval_choice_persist_action(choice: str) -> str | None:
    """Return the metadata action to persist for an approving choice."""
    record = _plan_approval_choice(choice)
    return None if record is None else record.persist_action


def approval_choice_archives_plan(choice: str) -> bool:
    """Return whether the approval choice should archive/copy the plan."""
    record = _plan_approval_choice(choice)
    return bool(record and record.archive_side_effect)


def custom_modal_choice_for_key(key: str) -> PlanApprovalModalChoice | None:
    """Return the custom-approval modal choice for a keyboard key."""
    for choice in PLAN_APPROVAL_MODAL_CHOICES:
        record = require_plan_approval_choice(choice)
        if record.custom_modal_key == key:
            return choice
    return None


def review_modal_choice_bindings() -> list[tuple[str, str, str]]:
    """Return Textual bindings for top-level plan-review approval choices."""
    bindings: list[tuple[str, str, str]] = []
    for choice in PLAN_APPROVAL_MODAL_CHOICES:
        record = require_plan_approval_choice(choice)
        if record.review_modal_key is not None:
            bindings.append((record.review_modal_key, record.id, record.display_label))
    return bindings


def review_modal_choice_hints_markup() -> str:
    """Return footer hint markup for top-level approval choices."""
    parts: list[str] = []
    for choice in PLAN_APPROVAL_MODAL_CHOICES:
        record = require_plan_approval_choice(choice)
        key = record.review_modal_key
        if key is None:
            continue
        color = "magenta" if choice == "epic" else "green"
        parts.append(f"[{color}]{key}[/{color}]={record.display_label}")
    return "  ".join(parts)
