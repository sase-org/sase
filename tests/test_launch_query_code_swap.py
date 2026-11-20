"""``sase run`` defers to a code swap before it starts and retries swap fallout."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

import pytest

from tests._workspace_provider_helpers import _patch_workflow_metadata, git_metadata


class _Stop(Exception):
    """Stands in for the re-exec, which never returns."""


def _launch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    launch_error: BaseException,
    retry: Any,
) -> list[dict[str, Any]]:
    from sase.main.query_handler import _launch

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_workflow_metadata(monkeypatch, git_metadata)
    emitted: list[dict[str, Any]] = []
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(_launch, "defer_launch_for_code_swap", lambda _argv: None)
        )
        stack.enter_context(
            patch.object(_launch, "retry_launch_after_code_swap", retry)
        )
        stack.enter_context(
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names",
                return_value=[],
            )
        )
        stack.enter_context(
            patch(
                "sase.macro.unresolved.scan_query_for_unresolved_references",
                return_value=(),
            )
        )
        stack.enter_context(
            patch.object(_launch, "launch_agents_from_cwd", side_effect=launch_error)
        )
        stack.enter_context(
            patch(
                "sase.ops.commands.run.emit_run_launch_result",
                side_effect=lambda **kwargs: emitted.append(kwargs),
            )
        )
        _launch.launch_query("do work")
    return emitted


def test_deferral_runs_before_the_launch_reads_or_records_anything() -> None:
    from sase.main.query_handler import _launch

    calls: list[list[str]] = []

    def fake_defer(argv: list[str]) -> None:
        calls.append(argv)
        raise _Stop

    with (
        patch.object(_launch, "defer_launch_for_code_swap", fake_defer),
        patch("sase.ops.cli.load_request") as load_request,
        pytest.raises(_Stop),
    ):
        _launch.launch_query("do work")

    assert calls and calls[0][1:3] == ["-m", "sase"]
    load_request.assert_not_called()


def test_swap_skew_launch_failure_is_offered_to_the_retry_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[BaseException] = []

    def fake_retry(exc: BaseException, argv: list[str]) -> None:
        seen.append(exc)
        raise _Stop

    error = ImportError("cannot import name 'BeforeSpawnCallback'")
    with pytest.raises(_Stop):
        _launch(monkeypatch, launch_error=error, retry=fake_retry)

    assert seen == [error]


def test_failure_the_retry_declines_is_reported_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[BaseException] = []

    with pytest.raises(SystemExit) as exc_info:
        _launch(
            monkeypatch,
            launch_error=RuntimeError("no workspace available"),
            retry=lambda exc, _argv: seen.append(exc),
        )

    assert exc_info.value.code == 1
    assert [str(exc) for exc in seen] == ["no workspace available"]


def test_partial_multi_prompt_launch_is_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

    seen: list[BaseException] = []
    error = MultiPromptPartialLaunchError([], RuntimeError("second segment failed"))

    with (
        patch(
            "sase.agent.partial_launch.rollback_partial_launch_results",
            return_value=type(
                "Rollback", (), {"terminated_pids": [], "released_workspaces": []}
            )(),
        ),
        pytest.raises(SystemExit),
    ):
        _launch(
            monkeypatch,
            launch_error=error,
            retry=lambda exc, _argv: seen.append(exc),
        )

    assert seen == []
