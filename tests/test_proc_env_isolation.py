"""Hermetic isolation of inherited supervisor proc environment.

Live SASE agent shells export ``SASE_PROC_*`` sidecars for the current
``run.launch`` operation. Pytest must not consume those paths unless a test
opts in with ``monkeypatch`` after fixture setup.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.ops import (
    OPERATION_ENV,
    PROC_ID_ENV,
    REQUEST_ENV,
    RESULT_ENV,
    DurableOperationRequest,
    emit_operation_result,
    load_request,
    resolve_proc_id,
    resolve_request_path,
    resolve_result_path,
    write_operation_request,
)


pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]

LIVE_PROC_ENV_VARS = (
    REQUEST_ENV,
    RESULT_ENV,
    OPERATION_ENV,
    PROC_ID_ENV,
    "SASE_PROC_LOG_PATH",
    "SASE_PROC_SESSION_ID",
)

_SASE_ML_FILE_FAMILIES = (
    "tests/test_gate_cli_answer.py::test_set_types_every_declared_input_field",
    "tests/test_gate_cli_act.py::test_run_command_action_repeats_and_leaves_the_gate_answerable",
    "tests/gate_conformance/test_gate_conformance.py::test_gate_conformance[cli-no_input]",
    "tests/main/test_ops_commands.py::test_patch_status_success_and_failure_results",
    "tests/test_special_cases.py::test_launch_query_from_agent_context_requests_approval",
    "tests/test_partial_launch_cleanup.py::test_launch_query_prints_each_launched_agent_pid",
    "tests/test_prompt_inputs.py::test_launch_query_errors_clearly_on_missing_required_inputs",
    "tests/test_multi_prompt_e2e.py::test_cli_single_prompt_launches_detached",
    "tests/ace/tui/modals/test_snippet_name_modal.py::test_escape_returns_none",
    "tests/test_config.py::test_deep_merge_list_concatenation",
    "tests/test_config_cache.py::test_clear_config_cache_forces_reload",
)


def _seed_live_proc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request_path = tmp_path / "operation-request.json"
    result_path = tmp_path / "operation-result.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(operation="run.launch", payload={"prompt": "host"}),
    )
    monkeypatch.setenv(REQUEST_ENV, str(request_path))
    monkeypatch.setenv(RESULT_ENV, str(result_path))
    monkeypatch.setenv(OPERATION_ENV, "run.launch")
    monkeypatch.setenv(PROC_ID_ENV, "host-live-proc")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "host.log"))
    monkeypatch.setenv("SASE_PROC_SESSION_ID", "host-session")


def test_autouse_fixture_scrubs_every_ambient_proc_variable() -> None:
    leaked = [key for key in os.environ if key.startswith("SASE_PROC_")]
    assert leaked == []
    assert resolve_request_path() is None
    assert resolve_result_path() is None
    assert resolve_proc_id() == ""


def test_ordinary_handlers_do_not_consume_caller_sidecars() -> None:
    loaded = load_request("gate.answer")
    assert loaded.operation == "gate.answer"
    assert dict(loaded.payload) == {}
    result = emit_operation_result(
        operation="gate.answer",
        success=True,
        message="answered",
    )
    assert result.operation == "gate.answer"
    assert result.proc_id == "direct"


def test_intentional_override_still_resolves_supervisor_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(operation="gate.answer", payload={"choice": "yes"}),
    )
    monkeypatch.setenv(REQUEST_ENV, str(request_path))
    monkeypatch.setenv(RESULT_ENV, str(result_path))
    monkeypatch.setenv(PROC_ID_ENV, "proc-override")
    monkeypatch.setenv(OPERATION_ENV, "gate.answer")

    assert resolve_request_path() == request_path
    assert resolve_result_path() == result_path
    assert resolve_proc_id() == "proc-override"
    loaded = load_request("gate.answer")
    assert dict(loaded.payload) == {"choice": "yes"}
    emitted = emit_operation_result(
        operation="ignored.operation",
        success=True,
        message="ok",
    )
    assert emitted.operation == "gate.answer"
    assert emitted.proc_id == "proc-override"
    assert result_path.is_file()


def test_sase_ml_file_families_ignore_inherited_live_proc_env(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _seed_live_proc_env(tmp_path, monkeypatch)
    for key in LIVE_PROC_ENV_VARS:
        assert key in os.environ

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        *[str(_ROOT / node) for node in _SASE_ML_FILE_FAMILIES],
        timeout=180,
    )
    result.assert_outcomes(passed=len(_SASE_ML_FILE_FAMILIES))
