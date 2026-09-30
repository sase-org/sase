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
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)


def _run_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    launch_mock: MagicMock,
    *,
    payload_extra: dict | None = None,
) -> None:
    """Run ``launch_query`` end to end with launch and emit mocked."""
    from sase.main.query_handler import _launch as launch_mod

    payload = {"prompt": prompt, **(payload_extra or {})}
    request = DurableOperationRequest(operation=RUN_LAUNCH, payload=payload)
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

    recorded = kwargs.get("history_text") or query
    assert isinstance(recorded, str)
    add_or_update_prompt(recorded, origin=kwargs.get("origin"))  # type: ignore[arg-type]
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

    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "toolrun-1")
    assert _sase_run_ingress_origin() == "generated"

    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "")
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


def test_toolrun_nested_run_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nested ToolRun child (SASE_AGENT cleared, marker set) records no row."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "toolrun-1")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch, "please record this terminal launch prompt now", launch_mock
        )

    assert launch_mock.call_args.kwargs.get("origin") == "generated"
    assert _load(history_file) == []


def test_toolrun_blank_marker_records_typed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank ToolRun marker does not suppress human history."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch, "please record this terminal launch prompt now", launch_mock
        )

    assert launch_mock.call_args.kwargs.get("origin") == "typed"
    (entry,) = _load(history_file)
    assert entry.origin == "typed"


def test_payload_history_origin_typed_does_not_upgrade_toolrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """history_origin=typed never upgrades a nested ToolRun back to history."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "toolrun-1")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please record this terminal launch prompt now",
            launch_mock,
            payload_extra={"history_origin": "typed"},
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


def test_run_forwards_payload_history_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A submitter rewrite (TUI provider guard) records the original text."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "remodeled member text launched here instead",
            launch_mock,
            payload_extra={
                "history_text": "please handle the original submission text now"
            },
        )

    assert (
        launch_mock.call_args.kwargs.get("history_text")
        == "please handle the original submission text now"
    )
    assert launch_mock.call_args.kwargs.get("origin") == "typed"
    (entry,) = _load(history_file)
    assert entry.text == "please handle the original submission text now"
    assert entry.origin == "typed"


def test_run_ignores_empty_payload_history_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty payload history_text falls back to the query."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please record this terminal launch prompt now",
            launch_mock,
            payload_extra={"history_text": "  "},
        )

    assert launch_mock.call_args.kwargs.get("history_text") is None
    (entry,) = _load(history_file)
    assert entry.text == "please record this terminal launch prompt now"


def test_force_reuse_records_pre_rewrite_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force-reuse passes the pre-rewrite query as history_text."""
    from sase.agent.force_reuse_launch import ForceReuseLaunchPlan

    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    plan = ForceReuseLaunchPlan(
        rewritten_prompt="rewritten reuse text launched here instead",
        owner_names=["worker"],
        segment_envs=[None],
    )
    monkeypatch.setattr(
        "sase.agent.force_reuse_launch.plan_force_reuse_launch", lambda _q: plan
    )
    monkeypatch.setattr(
        "sase.agent.force_reuse_launch.apply_force_reuse_launch", lambda _p: None
    )
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please reuse the worker name for this launch now",
            launch_mock,
            payload_extra={"allow_force_reuse": True},
        )

    assert (
        launch_mock.call_args.kwargs.get("history_text")
        == "please reuse the worker name for this launch now"
    )
    (entry,) = _load(history_file)
    assert entry.text == "please reuse the worker name for this launch now"
    assert entry.origin == "typed"


def test_payload_history_origin_generated_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """history_origin=generated overrides a plain-terminal ingress to nothing."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please record this terminal launch prompt now",
            launch_mock,
            payload_extra={"history_origin": "generated"},
        )

    assert launch_mock.call_args.kwargs.get("origin") == "generated"
    assert _load(history_file) == []


def test_payload_history_origin_unknown_value_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown history_origin value leaves the ingress origin alone."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please record this terminal launch prompt now",
            launch_mock,
            payload_extra={"history_origin": "bogus"},
        )

    assert launch_mock.call_args.kwargs.get("origin") == "typed"
    (entry,) = _load(history_file)
    assert entry.text == "please record this terminal launch prompt now"
    assert entry.origin == "typed"


def test_payload_history_origin_typed_does_not_upgrade_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """history_origin=typed never upgrades automation back to human history."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("SASE_MONITOR_ID", "monitor-1")
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please record this terminal launch prompt now",
            launch_mock,
            payload_extra={"history_origin": "typed"},
        )

    assert launch_mock.call_args.kwargs.get("origin") == "generated"
    assert _load(history_file) == []


def test_launch_units_payload_reaches_launcher_without_history_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """launch_units flow to the launcher; no payload text means no override."""
    history_file = _history_file(tmp_path)
    _clean_env(monkeypatch)
    launch_mock = MagicMock(side_effect=_recording_launch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        _run_launch_query(
            monkeypatch,
            "please handle the release checklist across units now",
            launch_mock,
            payload_extra={
                "launch_units": [
                    {
                        "prompt": "first unit prompt text here",
                        "template_group": None,
                        "swarm_xprompts": [],
                    }
                ]
            },
        )

    assert launch_mock.call_args.kwargs.get("history_text") is None
    assert launch_mock.call_args.kwargs.get("origin") == "typed"
    (unit,) = launch_mock.call_args.kwargs.get("launch_units")
    assert unit.prompt == "first unit prompt text here"
    (entry,) = _load(history_file)
    assert entry.text == "please handle the release checklist across units now"
