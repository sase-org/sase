"""Shared plan-approval option metadata and selected-set projections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, NamedTuple, cast

type PlanApprovalChoiceId = Literal[
    "approve",
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
type PlanApprovalTier = Literal["tale", "epic"]


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
PLAN_APPROVAL_AUTO_MODE_CHOICES = ("approve", "tale", "epic")


def plan_approval_selection_for_choice(
    choice: str,
    *,
    tier: PlanApprovalTier,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
) -> tuple[str, ...]:
    """Translate a product-facing approval action into v2 option ids.

    ``tale``/``run`` remain accepted as local aliases, but they are no longer
    authored as gate options. The default tale group selects both members.
    """
    if choice in {"reject", "feedback"}:
        return (choice,)
    if tier == "epic":
        if choice not in {"approve", "epic"}:
            raise KeyError(choice)
        return ("approve",)
    defaults = {
        "approve": (True, True),
        "run": (False, True),
        "tale": (True, True),
        "commit": (True, False),
    }
    try:
        default_commit, default_run = defaults[choice]
    except KeyError as exc:
        raise KeyError(choice) from exc
    effective_commit = default_commit if commit_plan is None else commit_plan
    effective_run = default_run if run_coder is None else run_coder
    selected = tuple(
        option_id
        for option_id, enabled in (
            ("approve", effective_run),
            ("commit", effective_commit),
        )
        if enabled
    )
    if not selected:
        raise ValueError("a tale approval must select approve, commit, or both")
    return selected


def plan_approval_protocol_for_selection(
    selected_option_ids: Sequence[str], *, tier: PlanApprovalTier
) -> PlanApprovalProtocolFields:
    """Derive the runner response protocol from one approval option set."""
    selected = tuple(selected_option_ids)
    if tier == "epic":
        if selected != ("approve",):
            raise ValueError("epic approval requires the approve option")
        return PlanApprovalProtocolFields("epic", True, True)
    if not selected or not set(selected) <= {"approve", "commit"}:
        raise ValueError("tale approval requires approve, commit, or both")
    return PlanApprovalProtocolFields(
        "approve",
        "commit" in selected,
        "approve" in selected,
    )


def plan_approval_status_for_selection(
    selected_option_ids: Sequence[str], *, tier: PlanApprovalTier
) -> str | None:
    """Return the immediate status label for a selected option set."""
    selected = tuple(selected_option_ids)
    if selected in {("reject",), ("feedback",)}:
        return None
    protocol = plan_approval_protocol_for_selection(selected, tier=tier)
    if protocol.action == "epic":
        return "EPIC APPROVED"
    if protocol.commit_plan and protocol.run_coder:
        return "TALE APPROVED"
    if protocol.commit_plan:
        return "PLAN COMMITTED"
    return "PLAN APPROVED"


def plan_approval_consequence_for_selection(
    selected_option_ids: Sequence[str], *, tier: PlanApprovalTier
) -> str:
    """Describe the consequences of one approval selection."""
    protocol = plan_approval_protocol_for_selection(selected_option_ids, tier=tier)
    if protocol.action == "epic":
        return (
            "Commit to sdd/plans (tier: epic); launch beads via `sase bead work` "
            "(background task)"
        )
    if protocol.commit_plan and protocol.run_coder:
        return "Commit to sdd/plans (tier: tale); run coder"
    if protocol.commit_plan:
        return "Commit to sdd/plans; do not run coder"
    return "No SDD commit; run coder"


def plan_approval_response_message_for_selection(
    selected_option_ids: Sequence[str], *, tier: PlanApprovalTier
) -> str:
    """Return the host-facing resolution message for selected options."""
    selected = tuple(selected_option_ids)
    if selected == ("reject",):
        return "Plan rejected"
    if selected == ("feedback",):
        return "Feedback received"
    protocol = plan_approval_protocol_for_selection(selected, tier=tier)
    if protocol.action == "epic":
        return "Epic approved"
    if protocol.commit_plan and protocol.run_coder:
        return "Tale approved"
    if protocol.commit_plan:
        return "Plan committed"
    return "Plan approved"


def _plan_approval_choice(choice: str) -> _PlanApprovalChoiceRecord | None:
    """Return the registered record for a choice string, if supported."""
    try:
        return require_plan_approval_choice(choice)
    except KeyError:
        return None


def require_plan_approval_choice(choice: str) -> _PlanApprovalChoiceRecord:
    """Return option metadata, accepting local pre-v2 action aliases."""
    record = _CHOICES_BY_ID.get(choice)
    if record is not None:
        return record
    approve = _CHOICES_BY_ID["approve"]
    if choice == "run":
        return replace(
            approve,
            id="approve",
            response_message="Running coder",
            cli_kind_name=None,
            allow_protocol_overrides=False,
        )
    if choice == "tale":
        return replace(
            approve,
            id="approve",
            display_label="Tale",
            response_message="Tale approved",
            protocol=PlanApprovalProtocolFields("approve", True, True),
            custom_modal_key="t",
            review_modal_key="t",
            consequence_text="Commit to sdd/plans (tier: tale); run coder",
            cli_kind_name="tale",
            auto_mode_eligible=True,
            persist_action="tale",
            status_label="TALE APPROVED",
        )
    if choice == "epic":
        return replace(
            approve,
            id="approve",
            display_label="Epic",
            response_message="Epic approved",
            protocol=PlanApprovalProtocolFields("epic", True, True),
            custom_modal_key="e",
            review_modal_key="E",
            consequence_text=(
                "Commit to sdd/plans (tier: epic); launch beads via "
                "`sase bead work` (background task)"
            ),
            archive_side_effect=False,
            cli_kind_name="epic",
            auto_mode_eligible=True,
            persist_action="epic",
            status_label="EPIC APPROVED",
            allow_protocol_overrides=False,
            allow_coder_options=False,
        )
    raise KeyError(choice)


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
    choice = {"a": "approve", "t": "tale", "e": "epic"}.get(key)
    return None if choice is None else cast(PlanApprovalModalChoice, choice)
