"""Tests for the shared plan-approval choice registry."""

from __future__ import annotations

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
    require_plan_approval_choice,
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
