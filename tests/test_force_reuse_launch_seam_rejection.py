"""Unauthorized-callers side of the forced-reuse launch seam.

Split from ``tests.test_force_reuse_launch_seam``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH

__all__ = [
    "test_plain_sase_run_without_request_sidecar_still_rejects_forced_reuse",
    "test_sidecar_without_authorization_still_rejects_forced_reuse",
]


def _run_launch_query_unauthorized(
    prompt: str,
    *,
    request: DurableOperationRequest | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.launch_validation import AgentNameReuseConfirmationRequiredError
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    load_request_patch = (
        patch("sase.ops.cli.load_request", return_value=request)
        if request is not None
        else patch("sase.ops.cli.resolve_request_path", return_value=None)
    )
    with (
        load_request_patch,
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=AgentNameReuseConfirmationRequiredError("foo"),
        ) as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        launch_query(prompt)

    assert excinfo.value.code == 1
    # No authorization means no force-reuse rewrite/wipe: the untouched
    # (still-``!``) prompt reaches the same validation the child always ran.
    mock_launch.assert_called_once()
    args, kwargs = mock_launch.call_args
    assert args == (prompt,)
    assert kwargs["origin"] == "typed"
    assert kwargs.get("history_text") is None


def test_plain_sase_run_without_request_sidecar_still_rejects_forced_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_launch_query_unauthorized(
        "%id:!foo\nDo work", request=None, monkeypatch=monkeypatch
    )


def test_sidecar_without_authorization_still_rejects_forced_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DurableOperationRequest(
        operation=RUN_LAUNCH,
        payload={"prompt": "%id:!foo\nDo work", "workflow": "w"},
    )
    _run_launch_query_unauthorized(
        "%id:!foo\nDo work", request=request, monkeypatch=monkeypatch
    )
