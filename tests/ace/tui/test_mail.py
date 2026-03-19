"""Tests for sase.ace.handlers.mail._mail_execute_task."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.ace.handlers.mail import _mail_execute_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_changespec(**overrides: object) -> MagicMock:
    """Create a mock ChangeSpec with sensible defaults."""
    cs = MagicMock()
    cs.name = overrides.get("name", "CL-1")
    cs.file_path = overrides.get("file_path", "/proj.gp")
    cs.project_basename = overrides.get("project_basename", "proj")
    cs.cl = overrides.get("cl", None)
    cs.parent = overrides.get("parent", None)
    return cs


# Patch targets
_PATCH_RELEASE = "sase.running_field.release_workspace"
_PATCH_TRANSITION = "sase.status_state_machine.transition_changespec_status"
_PATCH_EXECUTE_MAIL = "sase.ace.handlers.mail.execute_mail"


@pytest.fixture
def _patch_release():
    """Patch workspace release."""
    with patch(_PATCH_RELEASE) as m_release:
        yield m_release


@pytest.fixture
def _patch_transition():
    """Patch status transition with successful default."""
    with patch(
        _PATCH_TRANSITION, return_value=(True, "Ready", None, None)
    ) as m_trans:
        yield m_trans


@pytest.fixture
def _patch_execute_mail():
    """Patch execute_mail with successful default."""
    with patch(_PATCH_EXECUTE_MAIL, return_value=True) as m_exec:
        yield m_exec


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestMailExecuteTaskSuccess:
    def test_returns_success_on_mail_and_transition(
        self, _patch_release, _patch_transition, _patch_execute_mail
    ) -> None:
        cs = _make_changespec()
        success, message = _mail_execute_task(cs, "/ws/100", 100)

        assert success is True
        assert "Mailed CL-1" in message
        assert "Ready → Mailed" in message

    def test_returns_success_when_transition_fails(
        self, _patch_release, _patch_execute_mail
    ) -> None:
        """Mailing succeeded but status update failed — still success."""
        with patch(
            _PATCH_TRANSITION,
            return_value=(False, None, "invalid transition", None),
        ):
            cs = _make_changespec()
            success, message = _mail_execute_task(cs, "/ws/100", 100)

        assert success is True
        assert "status update failed" in message

    def test_calls_execute_mail_with_correct_args(
        self, _patch_release, _patch_transition, _patch_execute_mail
    ) -> None:
        cs = _make_changespec()
        _mail_execute_task(cs, "/ws/100", 100)

        _patch_execute_mail.assert_called_once()
        args = _patch_execute_mail.call_args
        assert args[0][0] is cs
        assert args[0][1] == "/ws/100"

    def test_calls_transition_with_correct_args(
        self, _patch_release, _patch_transition, _patch_execute_mail
    ) -> None:
        cs = _make_changespec()
        _mail_execute_task(cs, "/ws/100", 100)

        _patch_transition.assert_called_once_with(
            "/proj.gp", "CL-1", "Mailed", validate=True
        )


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


class TestMailExecuteTaskFailure:
    def test_returns_failure_when_execute_mail_fails(
        self, _patch_release
    ) -> None:
        with patch(_PATCH_EXECUTE_MAIL, return_value=False):
            cs = _make_changespec()
            success, message = _mail_execute_task(cs, "/ws/100", 100)

        assert success is False
        assert "Mail failed for CL-1" in message

    def test_does_not_transition_when_execute_mail_fails(
        self, _patch_release
    ) -> None:
        with (
            patch(_PATCH_EXECUTE_MAIL, return_value=False),
            patch(_PATCH_TRANSITION) as m_trans,
        ):
            cs = _make_changespec()
            _mail_execute_task(cs, "/ws/100", 100)

        m_trans.assert_not_called()


# ---------------------------------------------------------------------------
# Workspace lifecycle
# ---------------------------------------------------------------------------


class TestMailExecuteTaskWorkspaceLifecycle:
    def test_workspace_released_on_success(
        self, _patch_release, _patch_transition, _patch_execute_mail
    ) -> None:
        cs = _make_changespec()
        _mail_execute_task(cs, "/ws/100", 100)

        _patch_release.assert_called_once_with("/proj.gp", 100, "mail", "CL-1")

    def test_workspace_released_on_execute_mail_failure(
        self, _patch_release
    ) -> None:
        with patch(_PATCH_EXECUTE_MAIL, return_value=False):
            cs = _make_changespec()
            _mail_execute_task(cs, "/ws/100", 100)

        _patch_release.assert_called_once_with("/proj.gp", 100, "mail", "CL-1")

    def test_workspace_released_on_exception(
        self, _patch_release
    ) -> None:
        with patch(_PATCH_EXECUTE_MAIL, side_effect=Exception("boom")):
            cs = _make_changespec()
            with pytest.raises(Exception, match="boom"):
                _mail_execute_task(cs, "/ws/100", 100)

        _patch_release.assert_called_once_with("/proj.gp", 100, "mail", "CL-1")
