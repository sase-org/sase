"""Tests for the early Conventional Commit gate in ``CommitWorkflow``."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.message_validation import _CommitMessagePolicy
from sase.workflows.commit.workflow import CommitWorkflow
from sase.workflows.commit.workflow_types import RunResult


def _payload(method: str, message: str) -> dict[str, str]:
    payload = {"message": message}
    if method == "create_pull_request":
        payload["name"] = "message-gate-test"
    return payload


def _run_until_dispatch(
    payload: dict[str, str],
    method: str,
    *,
    policy: _CommitMessagePolicy | None = None,
) -> tuple[RunResult, MagicMock]:
    provider = MagicMock()
    provider.is_sync_in_progress.return_value = False
    provider.get_conflicted_files.return_value = []
    getattr(provider, method).return_value = (False, "stopped")

    with ExitStack() as stack:
        stack.enter_context(
            patch("sase.workflows.commit.workflow.apply_bead_commit_tag")
        )
        stack.enter_context(patch("sase.workflows.commit.workflow.handle_beads"))
        stack.enter_context(patch("sase.workflows.commit.workflow.handle_sase_plan"))
        stack.enter_context(
            patch(
                "sase.workflows.commit.workflow.run_before_commit_hook",
                return_value=True,
            )
        )
        stack.enter_context(
            patch("sase.workflows.commit.workflow.apply_project_pr_prefix")
        )
        stack.enter_context(patch("sase.workflows.commit.workflow.append_pr_tags"))
        stack.enter_context(
            patch("sase.workflows.commit.workflow.apply_runtime_commit_tags")
        )
        stack.enter_context(patch("sase.workflows.commit.workflow.build_pr_body"))
        stack.enter_context(
            patch(
                "sase.workflows.commit.workflow.detect_parent_changespec",
                return_value=None,
            )
        )
        stack.enter_context(
            patch("sase.workflows.utils.get_project_from_workspace", return_value=None)
        )
        stack.enter_context(
            patch(
                "sase.workflows.commit.workflow.get_vcs_provider",
                return_value=provider,
            )
        )
        stack.enter_context(
            patch("sase.workflows.commit.workflow.capture_pre_commit_diff")
        )
        stack.enter_context(patch("sase.workflows.commit.workflow.checkpoint_save"))
        stack.enter_context(patch("sase.workflows.commit.workflow.checkpoint_delete"))
        stack.enter_context(patch("sase.workflows.commit.workflow.cleanup_reservation"))
        if policy is not None:
            stack.enter_context(
                patch(
                    "sase.workflows.commit.workflow.load_commit_message_policy",
                    return_value=policy,
                )
            )
        result = CommitWorkflow(payload, method).run()

    return result, provider


def test_invalid_message_fails_before_side_effects_and_logs_reason() -> None:
    payload = _payload("create_commit", "Update built-in model aliases")
    provider = MagicMock()

    with (
        patch("sase.workflows.commit.workflow.apply_bead_commit_tag") as apply_tag,
        patch("sase.workflows.commit.workflow.handle_beads") as handle_beads,
        patch("sase.workflows.commit.workflow.handle_sase_plan") as handle_plan,
        patch("sase.workflows.commit.workflow.run_before_commit_hook") as before_hook,
        patch(
            "sase.workflows.commit.workflow.get_vcs_provider",
            return_value=provider,
        ) as get_provider,
        patch("sase.workflows.commit.workflow.print_status") as print_status,
        patch("sase.workflows.commit.workflow._log_commit_failed") as log_failed,
    ):
        result = CommitWorkflow(payload, "create_commit").run()

    assert result == RunResult.FAILED
    apply_tag.assert_not_called()
    handle_beads.assert_not_called()
    handle_plan.assert_not_called()
    before_hook.assert_not_called()
    get_provider.assert_not_called()
    provider.create_commit.assert_not_called()
    rejection = print_status.call_args.args[0]
    assert "Update built-in model aliases" in rejection
    assert "Expected: <type>[(<scope>)][!]: <description>" in rejection
    print_status.assert_called_once_with(rejection, "error")
    log_failed.assert_called_once_with("create_commit", "invalid_message")


@pytest.mark.parametrize(
    "method",
    ["create_commit", "create_proposal", "create_pull_request"],
)
def test_conventional_message_reaches_dispatch_unchanged(method: str) -> None:
    payload = _payload(method, "chore: leave the payload unchanged")

    result, provider = _run_until_dispatch(payload, method)

    assert result == RunResult.FAILED
    getattr(provider, method).assert_called_once_with(payload, ANY)
    assert payload == _payload(method, "chore: leave the payload unchanged")


def test_disabled_policy_allows_non_conventional_message() -> None:
    payload = _payload("create_commit", "Allow this project-specific subject")
    policy = _CommitMessagePolicy(require_conventional_subject=False)

    result, provider = _run_until_dispatch(payload, "create_commit", policy=policy)

    assert result == RunResult.FAILED
    provider.create_commit.assert_called_once_with(payload, ANY)


def test_exempt_subject_reaches_dispatch() -> None:
    payload = _payload("create_commit", "Merge branch 'message-gate'")

    result, provider = _run_until_dispatch(payload, "create_commit")

    assert result == RunResult.FAILED
    provider.create_commit.assert_called_once_with(payload, ANY)


@pytest.mark.parametrize(
    "method",
    ["create_commit", "create_proposal", "create_pull_request"],
)
def test_empty_message_is_rejected_for_every_method(method: str) -> None:
    payload = _payload(method, "")

    with (
        patch("sase.workflows.commit.workflow.get_vcs_provider") as get_provider,
        patch("sase.workflows.commit.workflow.print_status") as print_status,
        patch("sase.workflows.commit.workflow._log_commit_failed") as log_failed,
    ):
        result = CommitWorkflow(payload, method).run()

    assert result == RunResult.FAILED
    get_provider.assert_not_called()
    assert "the message is empty" in print_status.call_args.args[0]
    log_failed.assert_called_once_with(method, "invalid_message")
