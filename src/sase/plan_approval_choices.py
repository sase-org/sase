"""Shared plan-approval choice registry.

This is the approval-gate vocabulary source of truth. Phase 6 extends this
module with member options populated from agent-family definitions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

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
type PlanApprovalMemberAuto = Literal["run", "skip"]


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


@dataclass(frozen=True)
class PlanApprovalMemberOption:
    """A custom member option available at the plan-approval gate."""

    id: str
    display_label: str
    placement_after: str
    suffix: str
    auto: PlanApprovalMemberAuto
    default_enabled: bool
    definition_default: bool
    source_path: str
    config_id: str
    config_hash: str

    def as_request_payload(self) -> dict[str, object]:
        """Return the JSON-safe request payload for this member option."""
        return {
            "id": self.id,
            "label": self.display_label,
            "placement_after": self.placement_after,
            "suffix": self.suffix,
            "auto": self.auto,
            "default": self.default_enabled,
            "definition_default": self.definition_default,
            "source_path": self.source_path,
            "config_id": self.config_id,
            "config_hash": self.config_hash,
        }


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
            "Commit to sdd/plans (tier: epic); create beads and launch bead work"
        ),
        cli_kind_name="epic",
        archive_side_effect=True,
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


def _plan_approval_member_options(
    *,
    project: str | None = None,
    validate_prompt_refs: bool = True,
) -> tuple[PlanApprovalMemberOption, ...]:
    """Return custom member options available at the plan-approval gate."""

    from sase.agent_family.custom_definitions import get_all_agent_family_definitions

    default_overrides = _configured_plan_approval_member_defaults()
    roles_by_id: dict[str, Any] = {}
    for definition in get_all_agent_family_definitions(
        project=project,
        validate_prompt_refs=validate_prompt_refs,
    ).values():
        for role in definition.roles:
            roles_by_id[role.id] = role

    options: list[PlanApprovalMemberOption] = []
    for role_id in sorted(roles_by_id):
        role = roles_by_id[role_id]
        default_enabled = default_overrides.get(role.id, role.default_enabled)
        options.append(
            PlanApprovalMemberOption(
                id=role.id,
                display_label=role.id.replace("_", " "),
                placement_after=role.placement_after,
                suffix=role.suffix,
                auto=role.auto,
                default_enabled=default_enabled,
                definition_default=role.default_enabled,
                source_path=role.source_path,
                config_id=role.config_id,
                config_hash=role.config_hash,
            )
        )
    return tuple(options)


def plan_approval_member_request_payload(
    *,
    project: str | None = None,
    validate_prompt_refs: bool = True,
) -> dict[str, object]:
    """Return the member-option section stored in ``plan_request.json``."""

    options = _plan_approval_member_options(
        project=project,
        validate_prompt_refs=validate_prompt_refs,
    )
    return {
        "member_options": [option.as_request_payload() for option in options],
        "default_member_ids": [
            option.id for option in options if option.default_enabled
        ],
    }


def member_options_from_request_data(
    request_data: Mapping[str, object],
) -> tuple[PlanApprovalMemberOption, ...]:
    """Parse plan-approval member options from a request payload."""

    raw_options = request_data.get("member_options")
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, str):
        return ()

    parsed: list[PlanApprovalMemberOption] = []
    for raw in raw_options:
        if not isinstance(raw, Mapping):
            continue
        option_id = _clean_member_id(raw.get("id"))
        if option_id is None:
            continue
        auto = raw.get("auto")
        parsed.append(
            PlanApprovalMemberOption(
                id=option_id,
                display_label=_clean_str(raw.get("label")) or option_id,
                placement_after=_clean_str(raw.get("placement_after")) or "",
                suffix=_clean_str(raw.get("suffix")) or "",
                auto=auto if auto in {"run", "skip"} else "skip",
                default_enabled=raw.get("default") is True,
                definition_default=raw.get("definition_default") is True,
                source_path=_clean_str(raw.get("source_path")) or "",
                config_id=_clean_str(raw.get("config_id")) or "",
                config_hash=_clean_str(raw.get("config_hash")) or "",
            )
        )
    return tuple(parsed)


def default_member_ids_from_request_data(
    request_data: Mapping[str, object],
    *,
    auto_mode: bool = False,
) -> tuple[str, ...]:
    """Return selected member ids implied by the request defaults."""

    options = member_options_from_request_data(request_data)
    option_order = [option.id for option in options]
    option_ids = set(option_order)
    raw_default_ids = request_data.get("default_member_ids")
    if isinstance(raw_default_ids, Sequence) and not isinstance(raw_default_ids, str):
        default_ids = [
            member_id
            for raw in raw_default_ids
            if (member_id := _clean_member_id(raw)) in option_ids
        ]
    else:
        default_ids = [option.id for option in options if option.default_enabled]

    if auto_mode:
        auto_ids = {option.id for option in options if option.auto == "run"}
        default_ids = [member_id for member_id in default_ids if member_id in auto_ids]

    return tuple(member_id for member_id in option_order if member_id in default_ids)


def selected_member_ids_from_response_data(
    response_data: Mapping[str, object],
    request_data: Mapping[str, object],
) -> tuple[str, ...]:
    """Return explicit response selection or request defaults."""

    raw_selected = response_data.get("selected_member_ids")
    if isinstance(raw_selected, Sequence) and not isinstance(raw_selected, str):
        option_ids = {
            option.id for option in member_options_from_request_data(request_data)
        }
        if option_ids:
            return tuple(
                member_id
                for raw in raw_selected
                if (member_id := _clean_member_id(raw)) in option_ids
            )
        return tuple(
            member_id
            for raw in raw_selected
            if (member_id := _clean_member_id(raw)) is not None
        )
    return default_member_ids_from_request_data(request_data)


def resolve_member_selection_for_overrides(
    options: Sequence[PlanApprovalMemberOption],
    *,
    with_members: Sequence[str] = (),
    without_members: Sequence[str] = (),
) -> tuple[str, ...]:
    """Apply explicit with/without overrides to option defaults."""

    option_ids = {option.id for option in options}
    with_ids = _validated_member_override_ids(with_members, option_ids)
    without_ids = _validated_member_override_ids(without_members, option_ids)
    overlap = with_ids & without_ids
    if overlap:
        joined = ", ".join(sorted(overlap))
        raise ValueError(
            f"member option specified with both --with and --without: {joined}"
        )

    selected = {option.id for option in options if option.default_enabled}
    selected.update(with_ids)
    selected.difference_update(without_ids)
    return tuple(option.id for option in options if option.id in selected)


def filter_roles_by_selected_member_ids(
    roles: Sequence[Any],
    selected_member_ids: Sequence[str] | None,
) -> tuple[Any, ...]:
    """Filter custom-role definitions by explicit gate selection.

    ``None`` preserves the Phase 5 definition-driven behavior for legacy tests
    and direct internal callers. Real Phase 6 plan-gate responses pass a tuple,
    with an empty tuple meaning "run no custom members".
    """

    if selected_member_ids is None:
        return tuple(roles)
    selected = set(selected_member_ids)
    return tuple(role for role in roles if getattr(role, "id", None) in selected)


def _configured_plan_approval_member_defaults() -> dict[str, bool]:
    """Return project-local sticky default overrides for member options."""

    try:
        from sase.config import load_merged_config

        data = load_merged_config()
    except Exception:
        return {}
    agent_family = data.get("agent_family")
    if not isinstance(agent_family, Mapping):
        return {}
    plan_approval = agent_family.get("plan_approval")
    if not isinstance(plan_approval, Mapping):
        return {}
    raw_defaults = plan_approval.get("default_members")
    if isinstance(raw_defaults, Mapping):
        return {
            str(member_id): enabled
            for member_id, enabled in raw_defaults.items()
            if isinstance(member_id, str) and isinstance(enabled, bool)
        }
    if isinstance(raw_defaults, Sequence) and not isinstance(raw_defaults, str):
        return {
            member_id: True
            for raw in raw_defaults
            if (member_id := _clean_member_id(raw)) is not None
        }
    return {}


def _validated_member_override_ids(
    values: Sequence[str],
    option_ids: set[str],
) -> set[str]:
    cleaned = {
        member_id
        for value in values
        if (member_id := _clean_member_id(value)) is not None
    }
    unknown = cleaned - option_ids
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"unknown plan-approval member option: {joined}")
    return cleaned


def _clean_member_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clean_str(value: object) -> str | None:
    return _clean_member_id(value)
