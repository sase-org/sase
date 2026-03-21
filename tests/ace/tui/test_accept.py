"""Tests for sase.ace.tui.actions.proposal_rebase._accept_task."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.proposal_rebase import _accept_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_WORKFLOW = "sase.workflows.accept.AcceptWorkflow"
_PATCH_FORMAT_CONFLICT = "sase.workflows.accept.conflict_check.format_conflict_message"


def _make_mock_workflow(
    success: bool = True,
    conflict_result: MagicMock | None = None,
) -> MagicMock:
    """Create a mock AcceptWorkflow instance."""
    wf = MagicMock()
    wf.run.return_value = success
    wf.conflict_result = conflict_result
    return wf


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestAcceptTaskSuccess:
    def test_returns_success_single_proposal(self) -> None:
        wf = _make_mock_workflow(success=True)
        with patch(_PATCH_WORKFLOW, return_value=wf):
            success, message = _accept_task(
                [("2a", None)], "CL-1", "/proj.gp", False, False
            )

        assert success is True
        assert "Accepted proposal 2a" in message

    def test_returns_success_multiple_proposals(self) -> None:
        wf = _make_mock_workflow(success=True)
        with patch(_PATCH_WORKFLOW, return_value=wf):
            success, message = _accept_task(
                [("2a", None), ("2b", None)], "CL-1", "/proj.gp", False, False
            )

        assert success is True
        assert "Accepted proposals 2a, 2b" in message

    def test_includes_bookkeeping_suffix_when_skip_amend(self) -> None:
        wf = _make_mock_workflow(success=True)
        with patch(_PATCH_WORKFLOW, return_value=wf):
            success, message = _accept_task(
                [("2a", None)], "CL-1", "/proj.gp", False, True
            )

        assert success is True
        assert "bookkeeping only" in message

    def test_passes_correct_args_to_workflow(self) -> None:
        wf = _make_mock_workflow(success=True)
        with patch(_PATCH_WORKFLOW, return_value=wf) as mock_cls:
            _accept_task([("2a", "msg")], "CL-1", "/proj.gp", True, True)

        mock_cls.assert_called_once_with(
            proposals=[("2a", "msg")],
            cl_name="CL-1",
            project_file="/proj.gp",
            mark_ready_to_mail=True,
            skip_amend=True,
        )
        wf.run.assert_called_once()


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


class TestAcceptTaskFailure:
    def test_returns_failure_without_conflicts(self) -> None:
        wf = _make_mock_workflow(success=False, conflict_result=None)
        with patch(_PATCH_WORKFLOW, return_value=wf):
            success, message = _accept_task(
                [("2a", None)], "CL-1", "/proj.gp", False, False
            )

        assert success is False
        assert "Accept failed for CL-1" in message

    def test_returns_conflict_message_on_conflict(self) -> None:
        conflict = MagicMock()
        conflict.success = False
        wf = _make_mock_workflow(success=False, conflict_result=conflict)
        with (
            patch(_PATCH_WORKFLOW, return_value=wf),
            patch(
                _PATCH_FORMAT_CONFLICT,
                return_value="Conflicting pair: 2a and 2b",
            ) as mock_fmt,
        ):
            success, message = _accept_task(
                [("2a", None), ("2b", None)], "CL-1", "/proj.gp", False, False
            )

        assert success is False
        assert "Conflicting pair: 2a and 2b" in message
        mock_fmt.assert_called_once_with(conflict)

    def test_ignores_successful_conflict_result(self) -> None:
        """When conflict_result.success is True, it means no conflicts found
        (check passed). The workflow failed for another reason."""
        conflict = MagicMock()
        conflict.success = True
        wf = _make_mock_workflow(success=False, conflict_result=conflict)
        with patch(_PATCH_WORKFLOW, return_value=wf):
            success, message = _accept_task(
                [("2a", None)], "CL-1", "/proj.gp", False, False
            )

        assert success is False
        assert "Accept failed for CL-1" in message
