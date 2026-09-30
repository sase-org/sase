"""History ingress and root-prompt recording for ``sase run``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH


def _history_file(tmp_path: Path) -> Path:
    return tmp_path / "prompt_history.json"


def _load(history_file: Path) -> list:
    from sase.history.prompt_store import load_prompt_history

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        return load_prompt_history()


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)


def _run_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    launch_mock: MagicMock,
) -> None:
    """Run ``launch_query`` end to end with launch and emit mocked."""
    from sase.main.query_handler import _launch as launch_mod

    request = DurableOperationRequest(operation=RUN_LAUNCH, payload={"prompt": prompt})
    emit = MagicMock()
    monkeypatch.setattr("sase.ops.cli.load_request", lambda _name: request)
    monkeypatch.setattr(
        "sase.agent.prompt_inputs.missing_required_input_names", lambda _q: []
    )
    monkeypatch.setattr(
        "sase.xprompt.unresolved.scan_query_for_unresolved_references", lambda _q: []
    )
    monkeypatch.setattr(launch_mod, "launch_agents_from_cwd", launch_mock)
    monkeypatch.setattr("sase.ops.commands.run.emit_run_launch_result", emit)
    with pytest.raises(SystemExit) as exc_info:
        launch_mod.launch_query("ignored")
    assert exc_info.value.code == 0


def _recording_launch(query: str, **kwargs: object) -> list[object]:
    """Stand in for the launcher that still performs the real history write."""
    from sase.history.prompt import add_or_update_prompt

    add_or_update_prompt(query, origin=kwargs.get("origin"))  # type: ignore[arg-type]
    return [SimpleNamespace(pid=1)]


def test_ingress_origin_is_typed_on_a_plain_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import _sase_run_ingress_origin

    _clean_env(monkeypatch)
    assert _sase_run_ingress_origin() == "typed"


def test_ingress_origin_is_generated_under_automation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import _sase_run_ingress_origin

    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_MONITOR_ID", "monitor-1")
    assert _sase_run_ingress_origin() == "generated"

    _clean_env(monkeypatch)
    from sase.notification_gates.command_runner import GATE_COMMAND_ENV

    monkeypatch.setenv(GATE_COMMAND_ENV, "1")
    assert _sase_run_ingress_origin() == "generated"

    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_MONITOR_ID", "")
    assert _sase_run_ingress_origin() == "typed"


def test_plain_terminal_run_records_a_typed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch, "please record this terminal launch prompt now", launch_mock
        )

    assert launch_mock.call_args.kwargs.get("origin") == "typed"
    (entry,) = _load(history_file)
    assert entry.text == "please record this terminal launch prompt now"
    assert entry.origin == "typed"


def test_monitor_run_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_MONITOR_ID", "monitor-1")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch, "please record this terminal launch prompt now", launch_mock
        )

    assert launch_mock.call_args.kwargs.get("origin") == "generated"
    assert _load(history_file) == []


def test_gate_command_run_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.notification_gates.command_runner import GATE_COMMAND_ENV

    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv(GATE_COMMAND_ENV, "1")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch, "please record this terminal launch prompt now", launch_mock
        )

    assert launch_mock.call_args.kwargs.get("origin") == "generated"
    assert _load(history_file) == []


def _direct_admission_result(bundle_dir: Path) -> tuple[object, Path]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    result = SimpleNamespace(
        summary=None,
        launched_count=2,
        unit_results=[],
        results=[],
        admission_complete=True,
        plan_digest=None,
    )
    return result, bundle_dir


def test_direct_typed_admission_records_root_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.query_handler._launch import _dispatch_direct_typed_launch_if_active

    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    dispatched = _direct_admission_result(tmp_path / "bundle")
    monkeypatch.setattr(
        "sase.agent.direct_typed_launch.dispatch_direct_typed_launch",
        lambda *args, **kwargs: dispatched,
    )
    monkeypatch.setattr("sase.ops.commands.run.emit_run_launch_result", MagicMock())
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        pytest.raises(SystemExit) as exc_info,
    ):
        _dispatch_direct_typed_launch_if_active(
            "%proc(echo rewritten) do the thing",
            payload={},
            allow_force_reuse=False,
            unresolved_names=(),
            history_query="please admit this typed launch promptly now",
            history_origin="typed",
        )

    assert exc_info.value.code == 0
    (entry,) = _load(history_file)
    assert entry.text == "please admit this typed launch promptly now"
    assert entry.origin == "typed"
    assert entry.cancelled is False


def test_direct_typed_admission_failure_records_cancelled_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.launch_request_types import LaunchRequestError
    from sase.main.query_handler._launch import _dispatch_direct_typed_launch_if_active

    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    stashed: list[str] = []
    monkeypatch.setattr(
        "sase.agent.direct_typed_launch.dispatch_direct_typed_launch",
        MagicMock(side_effect=LaunchRequestError("invalid_request", "prompt", "boom")),
    )
    monkeypatch.setattr(
        "sase.agent.failed_launch_prompt_stash.stash_failed_launch_prompt",
        lambda text, **kwargs: stashed.append(text),
    )
    monkeypatch.setattr("sase.ops.commands.run.emit_run_launch_result", MagicMock())
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        pytest.raises(SystemExit),
    ):
        _dispatch_direct_typed_launch_if_active(
            "%proc(echo rewritten) do the thing",
            payload={},
            allow_force_reuse=False,
            unresolved_names=(),
            history_query="please admit this typed launch promptly now",
            history_origin="typed",
        )

    (entry,) = _load(history_file)
    assert entry.text == "please admit this typed launch promptly now"
    assert entry.cancelled is True
    assert stashed == ["please admit this typed launch promptly now"]


def _dispatch_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    dispatch_mock: MagicMock,
    *,
    expect_code: int = 0,
) -> None:
    """Run ``launch_query`` with remote dispatch mocked."""
    from sase.main.query_handler import _launch as launch_mod

    request = DurableOperationRequest(operation=RUN_LAUNCH, payload={"prompt": prompt})
    monkeypatch.setattr("sase.ops.cli.load_request", lambda _name: request)
    monkeypatch.setattr(
        "sase.agent.prompt_inputs.missing_required_input_names", lambda _q: []
    )
    monkeypatch.setattr(
        "sase.xprompt.unresolved.scan_query_for_unresolved_references", lambda _q: []
    )
    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", dispatch_mock)
    monkeypatch.setattr("sase.ops.commands.run.emit_run_launch_result", MagicMock())
    with pytest.raises(SystemExit) as exc_info:
        launch_mod.launch_query("ignored")
    assert exc_info.value.code == expect_code


def test_remote_dispatch_records_forwarded_root_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    dispatch_mock = MagicMock(
        return_value=SimpleNamespace(message="Dispatched launch", payload={})
    )
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _dispatch_launch_query(
            monkeypatch, "please dispatch this prompt remotely now", dispatch_mock
        )

    (entry,) = _load(history_file)
    assert entry.text == "please dispatch this prompt remotely now"
    assert entry.origin == "typed"


def test_remote_dispatch_failure_records_cancelled_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.dispatch.launch import RemoteDispatchLaunchError

    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    stashed: list[str] = []
    monkeypatch.setattr(
        "sase.agent.failed_launch_prompt_stash.stash_failed_launch_prompt",
        lambda text, **kwargs: stashed.append(text),
    )
    dispatch_mock = MagicMock(
        side_effect=RemoteDispatchLaunchError("remote target refused the launch")
    )
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _dispatch_launch_query(
            monkeypatch,
            "please dispatch this prompt remotely now",
            dispatch_mock,
            expect_code=1,
        )

    (entry,) = _load(history_file)
    assert entry.text == "please dispatch this prompt remotely now"
    assert entry.cancelled is True
    assert stashed == ["please dispatch this prompt remotely now"]
