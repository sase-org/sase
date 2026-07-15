"""Tests for the shared plan-approval choice registry."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from sase.plan_approval_choices import (
    PLAN_APPROVAL_AUTO_MODE_CHOICES,
    PLAN_APPROVAL_CHOICE_IDS,
    PLAN_APPROVAL_CLI_KINDS,
    PLAN_APPROVAL_MODAL_CHOICES,
    PLAN_APPROVAL_REMOTE_CHOICES,
    PlanApprovalProtocolFields,
    approval_protocol_for_choice,
    custom_modal_choice_for_key,
    default_member_ids_from_request_data,
    filter_roles_by_selected_member_ids,
    member_options_from_request_data,
    plan_approval_member_request_payload,
    require_plan_approval_choice,
    resolve_member_selection_for_overrides,
    selected_member_ids_from_response_data,
)


def test_registry_exposes_existing_local_surface_vocabularies() -> None:
    assert PLAN_APPROVAL_MODAL_CHOICES == ("approve", "tale", "epic")
    assert PLAN_APPROVAL_CLI_KINDS == (
        "approve",
        "commit",
        "epic",
        "tale",
    )
    assert PLAN_APPROVAL_AUTO_MODE_CHOICES == ("approve", "tale", "epic")

    for choice in (*PLAN_APPROVAL_MODAL_CHOICES, *PLAN_APPROVAL_CLI_KINDS):
        assert choice in PLAN_APPROVAL_CHOICE_IDS

    assert custom_modal_choice_for_key("a") == "approve"
    assert custom_modal_choice_for_key("t") == "tale"
    assert custom_modal_choice_for_key("e") == "epic"


def test_run_choice_is_first_class_no_commit_approval() -> None:
    record = require_plan_approval_choice("run")

    assert approval_protocol_for_choice("run") == PlanApprovalProtocolFields(
        action="approve",
        commit_plan=False,
        run_coder=True,
    )
    assert record.archive_side_effect is True
    assert record.persist_action == "approve"
    assert record.response_message == "Running coder"
    assert record.cli_kind_name is None


def test_epic_choice_delegates_archive_and_launch_to_bead_work() -> None:
    record = require_plan_approval_choice("epic")

    assert record.archive_side_effect is False
    assert "`sase bead work`" in record.consequence_text
    assert "background task" in record.consequence_text


def test_external_plan_choice_snapshot_matches_registry() -> None:
    # Cross-repo anchors this snapshot protects:
    # - sase-core: crates/sase_core/src/notifications/mobile.rs::PlanActionChoiceWire
    # - sase-telegram: src/sase_telegram/formatting.py PlanApproval callbacks
    assert PLAN_APPROVAL_REMOTE_CHOICES == (
        "approve",
        "run",
        "reject",
        "epic",
        "feedback",
    )
    for choice in PLAN_APPROVAL_REMOTE_CHOICES:
        assert require_plan_approval_choice(choice).id == choice


def test_retired_choice_tables_stay_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    source_files = [
        root / "src/sase/ace/tui/modals/plan_approval_modal.py",
        root / "src/sase/ace/tui/modals/approve_options_modal.py",
    ]
    retired_names = {
        "_PLAN_APPROVAL_CHOICE_PROTOCOL",
        "_CHOICE_KEYS",
        "_CHOICE_LABELS",
        "_CHOICE_CONSEQUENCES",
    }

    for source_file in source_files:
        text = source_file.read_text(encoding="utf-8")
        for retired_name in retired_names:
            assert retired_name not in text


def _role(
    role_id: str,
    *,
    default_enabled: bool = False,
    auto: str = "run",
    placement_after: str = "code",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=role_id,
        suffix=f"--{role_id}",
        placement_after=placement_after,
        auto=auto,
        default_enabled=default_enabled,
        source_path=f"/xprompts/{role_id}.yml",
        config_id=role_id,
        config_hash=f"hash-{role_id}",
    )


def test_member_options_apply_definition_and_project_defaults(monkeypatch) -> None:
    tester = _role("tester", default_enabled=True)
    improve = _role("improve_plan", auto="skip", placement_after="plan")
    definition = SimpleNamespace(roles=(tester, improve))

    monkeypatch.setattr(
        "sase.agent_family.custom_definitions.get_all_agent_family_definitions",
        lambda **_kwargs: {"demo": definition},
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "agent_family": {
                "plan_approval": {
                    "default_members": {
                        "improve_plan": True,
                        "tester": False,
                    }
                }
            }
        },
    )

    payload = plan_approval_member_request_payload(validate_prompt_refs=False)
    options = member_options_from_request_data(payload)

    assert [(option.id, option.default_enabled) for option in options] == [
        ("improve_plan", True),
        ("tester", False),
    ]
    assert payload["default_member_ids"] == ["improve_plan"]
    assert options[0].placement_after == "plan"


def test_member_request_parsing_and_selection_overrides() -> None:
    request_data = {
        "member_options": [
            {
                "id": "improve_plan",
                "label": "improve plan",
                "placement_after": "plan",
                "suffix": "--improve_plan",
                "auto": "skip",
                "default": True,
                "definition_default": False,
                "source_path": "/x/improve.yml",
                "config_id": "improve_plan",
                "config_hash": "abc",
            },
            {
                "id": "tester",
                "label": "tester",
                "placement_after": "code",
                "suffix": "--tester",
                "auto": "run",
                "default": False,
                "definition_default": False,
                "source_path": "/x/tester.yml",
                "config_id": "tester",
                "config_hash": "def",
            },
        ],
        "default_member_ids": ["improve_plan"],
    }

    options = member_options_from_request_data(request_data)

    assert [option.id for option in options] == ["improve_plan", "tester"]
    assert default_member_ids_from_request_data(request_data) == ("improve_plan",)
    assert default_member_ids_from_request_data(request_data, auto_mode=True) == ()
    assert selected_member_ids_from_response_data({}, request_data) == ("improve_plan",)
    assert selected_member_ids_from_response_data(
        {"selected_member_ids": ["tester", "missing"]},
        request_data,
    ) == ("tester",)
    assert resolve_member_selection_for_overrides(
        options,
        with_members=("tester",),
        without_members=("improve_plan",),
    ) == ("tester",)


def test_filter_roles_by_selected_member_ids_preserves_legacy_none() -> None:
    roles = (_role("improve_plan"), _role("tester"))

    assert filter_roles_by_selected_member_ids(roles, None) == roles
    assert filter_roles_by_selected_member_ids(roles, ("tester",)) == (roles[1],)
    assert filter_roles_by_selected_member_ids(roles, ()) == ()
