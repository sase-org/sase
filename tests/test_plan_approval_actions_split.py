"""Public-surface and size regression tests for the plan approval split.

``plan_approval_actions`` is a facade: response execution lives in
``sase._plan_approval_response`` and terminal side effects live in
``sase._plan_approval_side_effects``. These tests pin the facade contract
that gate adapters, the TUI, and mobile side effects resolve lazily, plus
the per-file line budget the split was made for.
"""

from __future__ import annotations

from pathlib import Path

import sase._plan_approval_response as plan_response
import sase._plan_approval_side_effects as plan_side_effects
import sase.plan_approval_actions as facade

MAX_SPLIT_FILE_LINES = 500

SPLIT_FILES = (
    "src/sase/plan_approval_actions.py",
    "src/sase/_plan_approval_response.py",
    "src/sase/_plan_approval_side_effects.py",
)

# Every runtime name the facade exposed before the split, including the
# private attributes tests stub via monkeypatch/patch.
FACADE_CONTRACT = (
    "EpicLaunchMode",
    "HOST_PLAN_ARCHIVE_PROTOCOL",
    "PLAN_APPROVAL_ACTIONS",
    "PLAN_APPROVAL_KINDS",
    "PlanApprovalActionContext",
    "PlanApprovalActionError",
    "PlanApprovalActionResult",
    "PlanApprovalValidationError",
    "_archive_plan_for_approval",
    "_epic_launch_project",
    "_persist_plan_approved_metadata",
    "_resolve_plan_approval_choice",
    "apply_plan_post_terminal_side_effects",
    "can_claim_epic_launch",
    "dismiss_notification_best_effort",
    "durable_plan_file_for_context",
    "execute_plan_approval_response",
    "persisted_plan_action",
    "plan_approval_response_message_for_selection",
    "plan_approval_selection_for_choice",
    "plan_response_json",
    "plan_response_json_for_selection",
    "preflight_plan_archive_credential",
    "prepare_epic_launch",
    "prepare_plan_terminal_response",
    "require_plan_approval_validation",
    "resolve_plan_agent_artifacts_dir",
    "run_plan_side_effects",
    "update_agent_artifact_index_for_marker_mutation",
)


def test_facade_preserves_public_surface() -> None:
    for name in FACADE_CONTRACT:
        assert hasattr(facade, name), f"facade lost attribute: {name}"


def test_implementation_homes_expose_canonical_helpers() -> None:
    assert (
        facade._execute_neutral_plan_approval_response
        is plan_response.execute_neutral_plan_approval_response
    )
    assert (
        facade._archive_plan_for_approval is plan_side_effects.archive_plan_for_approval
    )
    assert (
        facade.apply_plan_post_terminal_side_effects
        is plan_side_effects.apply_plan_post_terminal_side_effects
    )


def test_split_files_stay_within_line_budget() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative in SPLIT_FILES:
        lines = (repo_root / relative).read_text(encoding="utf-8").splitlines()
        assert len(lines) <= MAX_SPLIT_FILE_LINES, (
            f"{relative} has {len(lines)} lines (budget {MAX_SPLIT_FILE_LINES})"
        )
