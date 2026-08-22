"""Sandboxed `%if` admission runtime over the Rust condition evaluator.

The coordinator journals ``checking``, then this module materializes a private
script and ``SASE_CONDITION_CONTEXT`` JSON file, supervises a process group,
and settles exit 0 as eligible, exit 1 as skipped, and every other result as a
condition error. False and error outcomes never allocate a runner, workspace,
agent, or proc identity.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_launch_facade import (
    build_condition_context,
    classify_condition_status,
    evaluate_launch_condition as rust_evaluate_launch_condition,
    sanitize_condition_inputs,
)
from sase.core.agent_launch_wire import (
    LaunchConditionWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding

CHECK_FILENAME = "check.json"
RESULT_FILENAME = "result.json"
REQUEST_FILENAME = "request.json"
CANCEL_FILENAME = "cancel"
UNITS_DIRNAME = "units"
_POLL_SECONDS = 0.05
_GRACE_SECONDS = 2.0


def evaluate_launch_condition(
    unit: LaunchUnitWire,
    waited_outcomes: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Default coordinator hook: sandbox ``unit.condition`` and return a verdict."""

    if unit.condition is None:
        return "eligible", None
    if not isinstance(unit.condition, LaunchConditionWire):
        return "condition_error", "invalid_condition"
    work_dir = _work_dir(context, unit.logical_id)
    recovered = recover_launch_condition(work_dir)
    if recovered is not None:
        return recovered
    request = _request_from_unit(unit, waited_outcomes, context, work_dir)
    if bool(context.get("supervise", True)):
        return _supervise_request(request, work_dir, context)
    result = rust_evaluate_launch_condition(request)
    return _verdict_from_result(result)


def recover_launch_condition(
    work_dir: Path,
    *,
    timeout_seconds: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[str, str | None] | None:
    """Return a proven predicate result without re-running the program."""

    proven = _read_result(work_dir)
    if proven is not None:
        return proven
    check = _read_json(work_dir / CHECK_FILENAME)
    if check is None:
        return None
    pid = check.get("pid")
    pgid = check.get("pgid")
    if not isinstance(pid, int) or pid <= 0 or not _pid_is_running(pid):
        leftover = pgid if isinstance(pgid, int) else pid
        if isinstance(leftover, int) and leftover > 0:
            _kill_group(leftover)
        return None
    deadline = time.monotonic() + _recover_timeout(timeout_seconds)
    stop = cancelled or (lambda: False)
    while time.monotonic() < deadline:
        if stop():
            _kill_group(int(pgid) if isinstance(pgid, int) else pid)
            return "condition_error", "cancelled"
        proven = _read_result(work_dir)
        if proven is not None:
            return proven
        if not _pid_is_running(pid):
            break
        time.sleep(_POLL_SECONDS)
    proven = _read_result(work_dir)
    if proven is not None:
        return proven
    _kill_group(int(pgid) if isinstance(pgid, int) else pid)
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "usage: python -m sase.agent.launch_condition_runtime <request.json>",
            file=sys.stderr,
        )
        return 2
    request_path = Path(args[0])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        return 2
    rust_evaluate_launch_condition(request)
    return 0


def _request_from_unit(
    unit: LaunchUnitWire,
    waited_outcomes: list[dict[str, Any]],
    context: Mapping[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    condition = unit.condition
    assert isinstance(condition, LaunchConditionWire)
    waited = [item for item in waited_outcomes if isinstance(item, Mapping)]
    rust_waited = [dict(item) for item in waited]
    selected_project = context.get("selected_project")
    if selected_project is not None:
        selected_project = str(selected_project)
    built = build_condition_context(
        unit,
        rust_waited,
        selected_project=selected_project,
        safe_inputs=_safe_inputs(context),
        share_workspace=False,
    )
    cwd = condition.cwd or context.get("source_cwd")
    timeout = context.get("timeout_seconds")
    output_cap = context.get("output_cap_bytes")
    python_executable = str(context.get("python_executable") or sys.executable)
    work_dir.mkdir(parents=True, exist_ok=True)
    cancel_path = work_dir / CANCEL_FILENAME
    schema = int(require_rust_binding("condition_eval_wire_schema_version")())
    return {
        "schema_version": schema,
        "logical_id": unit.logical_id,
        "code": agent_launch_wire_to_json_dict(condition.code),
        "work_dir": str(work_dir),
        "python_executable": python_executable,
        "cwd": None if cwd is None else str(cwd),
        "timeout_seconds": None if timeout is None else float(timeout),
        "output_cap_bytes": None if output_cap is None else int(output_cap),
        "context": built,
        "cancel_path": str(cancel_path),
        "share_workspace": False,
    }


def _supervise_request(
    request: dict[str, Any],
    work_dir: Path,
    context: Mapping[str, Any],
) -> tuple[str, str | None]:
    work_dir.mkdir(parents=True, exist_ok=True)
    request_path = work_dir / REQUEST_FILENAME
    _write_private_json(request_path, request)
    env = os.environ.copy()
    from sase.agent.env_hygiene import scrub_agent_identity_env, scrub_chop_context_env

    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sase.agent.launch_condition_runtime",
            str(request_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        cwd=str(work_dir),
        env=env,
    )
    timeout = float(
        request.get("timeout_seconds")
        or require_rust_binding("condition_default_timeout_seconds")()
    )
    deadline = time.monotonic() + timeout + _GRACE_SECONDS
    stop = context.get("cancelled")
    cancelled = stop if callable(stop) else (lambda: False)
    while child.poll() is None:
        if cancelled():
            (work_dir / CANCEL_FILENAME).write_text("1\n", encoding="utf-8")
            _kill_group(child.pid)
            try:
                child.wait(timeout=_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_group(child.pid)
            return "condition_error", "cancelled"
        if time.monotonic() >= deadline:
            (work_dir / CANCEL_FILENAME).write_text("1\n", encoding="utf-8")
            _kill_group(child.pid)
            try:
                child.wait(timeout=_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_group(child.pid)
            proven = _read_result(work_dir)
            return (
                proven
                if proven is not None
                else ("condition_error", "condition timed out")
            )
        time.sleep(_POLL_SECONDS)
    proven = _read_result(work_dir)
    if proven is not None:
        return proven
    return "condition_error", "condition_evaluator_unavailable"


def _work_dir(context: Mapping[str, Any], logical_id: str) -> Path:
    raw = context.get("work_dir")
    if raw:
        return Path(str(raw))
    admission_dir = context.get("admission_dir")
    if admission_dir:
        return Path(str(admission_dir)) / UNITS_DIRNAME / logical_id
    return Path.cwd() / "launch_condition" / logical_id


def _safe_inputs(context: Mapping[str, Any]) -> dict[str, Any]:
    raw = context.get("safe_inputs")
    if not isinstance(raw, Mapping):
        return {}
    return sanitize_condition_inputs(dict(raw))


def _verdict_from_result(result: Mapping[str, Any]) -> tuple[str, str | None]:
    verdict = str(result.get("verdict") or "")
    if verdict not in {"eligible", "skipped", "condition_error"}:
        exit_code = result.get("exit_code")
        signal = result.get("signal")
        verdict = classify_condition_status(
            exit_code=exit_code if isinstance(exit_code, int) else None,
            signal=signal if isinstance(signal, int) else None,
            timed_out=bool(result.get("timed_out")),
            exec_error=bool(result.get("exec_error")),
            cancelled=bool(result.get("cancelled")),
        )
    message = result.get("message")
    return verdict, None if message is None else str(message)


def _read_result(work_dir: Path) -> tuple[str, str | None] | None:
    payload = _read_json(work_dir / RESULT_FILENAME)
    if payload is None:
        return None
    return _verdict_from_result(payload)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), sort_keys=True).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _recover_timeout(timeout_seconds: float | None) -> float:
    if timeout_seconds is not None:
        return float(timeout_seconds)
    return (
        float(require_rust_binding("condition_default_timeout_seconds")())
        + _GRACE_SECONDS
    )


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            return


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except (OSError, IndexError):
        return True
    return state != "Z"


if __name__ == "__main__":
    raise SystemExit(main())
