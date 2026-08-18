"""Host-side effects of the PluginsRequired install decision."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.plugins._required_gate_response import PluginsRequiredResponse
from sase.plugins.required_gate import apply_plugins_required_decision


def _response(**overrides: Any) -> PluginsRequiredResponse:
    fields: dict[str, Any] = {
        "action": "install",
        "project": "sase",
        "installed": ("sase-github",),
        "changed": True,
        "source": "tui",
    }
    fields.update(overrides)
    return PluginsRequiredResponse(**fields)


def test_apply_install_restarts_axe_when_code_changed() -> None:
    restart = MagicMock()
    with (
        patch(
            "sase.axe.process.is_axe_running",
            return_value=True,
        ),
        patch(
            "sase.axe.process.restart_axe_daemon_result",
            return_value=MagicMock(succeeded=True, pid=9, attempts=1, verified=True),
        ),
        patch(
            "sase.main.update_restart.restart_after_update",
            restart,
        ),
    ):
        apply_plugins_required_decision(_response(changed=True))

    restart.assert_called_once()
    assert restart.call_args.kwargs["changed"] is True
    assert restart.call_args.kwargs["source"] == "sase plugin install"


def test_apply_install_skips_restart_when_unchanged() -> None:
    restart = MagicMock()
    with patch("sase.main.update_restart.restart_after_update", restart):
        apply_plugins_required_decision(_response(changed=False))
    restart.assert_not_called()


def test_apply_dismiss_is_a_noop() -> None:
    restart = MagicMock()
    with patch("sase.main.update_restart.restart_after_update", restart):
        apply_plugins_required_decision(_response(action="dismiss", changed=False))
    restart.assert_not_called()
