"""Execution of constrained ``builtin@command`` finalizers."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.artifacts import (
    instance_artifact_dir,
    write_json_atomic,
    write_text_artifact,
)
from sase.finalizers.bounded_subprocess import (
    BoundedCompletedProcess,
    clamp_timeout_seconds,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.bounded_subprocess import cleanup_live_sink
from sase.finalizers.executor_support import (
    FinalizerExecutionContext,
    FinalizerExecutionError,
    failed_result,
    op_channel_paths,
    op_progress_tick,
    op_steps_extra,
    retain_live_sink,
    run_subprocess,
    sanitized_env,
)
from sase.finalizers.steps import live_file_for, steps_file_for
from sase.finalizers.ledger import InstanceLedger, run_budgeted_attempts
from sase.finalizers.operation_records import OperationRecorder
from sase.finalizers.providers import (
    CommandFinalizerConfig,
    fatal_provider_diagnostics,
    parse_command_finalizer_config,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir


def execute_command_finalizer(
    instance: ConfiguredFinalizerInstance,
    context: FinalizerExecutionContext,
    *,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Run a constrained ``builtin@command`` finalizer."""

    command_config, diagnostics = parse_command_finalizer_config(instance)
    fatal = fatal_provider_diagnostics(diagnostics)
    if command_config is None or fatal:
        return failed_result(
            instance.instance_id,
            "invalid_command_config",
            fatal[0].message if fatal else "invalid builtin@command config",
        )

    owned = ledger or InstanceLedger(
        instance.instance_id, max(1, instance.max_attempts)
    )

    def run_once() -> FinalizerInstanceResultWire:
        return _execute_command_once(instance, command_config, context, owned)

    if ledger is None:
        return run_budgeted_attempts(owned, run_once)
    return run_once()


def _execute_command_once(
    instance: ConfiguredFinalizerInstance,
    command_config: CommandFinalizerConfig,
    context: FinalizerExecutionContext,
    ledger: InstanceLedger,
) -> FinalizerInstanceResultWire:
    attempt = ledger.consume_before_execute()
    result = _run_command_attempt(instance, command_config, context, attempt)
    if result["returncode"] == 0:
        return FinalizerInstanceResultWire(
            instance_id=instance.instance_id,
            status="success",
            attempts=[FinalizerAttemptWire(attempt=attempt, status="success")],
            evidence=result["evidence"],
        )
    code = str(result["diagnostic_code"])
    return FinalizerInstanceResultWire(
        instance_id=instance.instance_id,
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=attempt,
                status="failed",
                diagnostic_code=code,
            )
        ],
        evidence=result["evidence"],
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=(
                    f"builtin@command {instance.instance_id!r} failed on "
                    f"attempt {attempt}"
                ),
                instance_id=instance.instance_id,
                attempt=attempt,
            )
        ],
    )


def _run_command_attempt(
    instance: ConfiguredFinalizerInstance,
    command_config: CommandFinalizerConfig,
    context: FinalizerExecutionContext,
    attempt: int,
) -> dict[str, Any]:
    recorder = OperationRecorder.for_context(context, instance.instance_id)
    label = " ".join(command_config.command)[:120] or "command"
    started_at = recorder.start(
        "command", kind="subprocess", label=label, attempt=attempt
    )
    prefix = f"attempt-{attempt}.command"
    steps_path, live_path = op_channel_paths(context, instance.instance_id, prefix)
    started = time.monotonic()
    completed = run_subprocess(
        list(command_config.command),
        cwd=_resolve_cwd(command_config),
        env=sanitized_env(command_config.env, extra=op_steps_extra(steps_path)),
        input_bytes=None,
        timeout=clamp_timeout_seconds(command_config.timeout_seconds),
        live_path=live_path,
        progress_tick=op_progress_tick(context, instance.instance_id, steps_path),
    )
    duration = completed.duration_seconds or (time.monotonic() - started)
    _write_command_attempt_artifacts(
        instance,
        attempt,
        context,
        completed,
        recorder,
        started_at,
        label,
        argv=list(command_config.command),
        steps_path=steps_path,
        live_path=live_path,
    )
    evidence = [
        FinalizerOutcomeEvidenceWire(kind="exit_code", value=str(completed.returncode)),
        FinalizerOutcomeEvidenceWire(kind="duration_seconds", value=f"{duration:.3f}"),
    ]
    if completed.timed_out:
        return {
            "returncode": 124,
            "diagnostic_code": "command_timeout",
            "evidence": evidence,
        }
    if completed.stdout_truncated or completed.stderr_truncated:
        return {
            "returncode": 125,
            "diagnostic_code": "command_output_cap",
            "evidence": evidence,
        }
    return {
        "returncode": completed.returncode,
        "diagnostic_code": "command_failed",
        "evidence": evidence,
    }


def _write_command_attempt_artifacts(
    instance: ConfiguredFinalizerInstance,
    attempt: int,
    context: FinalizerExecutionContext,
    completed: BoundedCompletedProcess,
    recorder: OperationRecorder | None = None,
    started_at: float | None = None,
    label: str = "command",
    argv: list[str] | None = None,
    steps_path: str | None = None,
    live_path: str | None = None,
) -> None:
    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance.instance_id)
    if artifact_dir is None:
        return
    _write_exclusive_text(
        artifact_dir / f"attempt-{attempt}.stdout",
        completed.stdout.decode("utf-8", errors="replace"),
    )
    _write_exclusive_text(
        artifact_dir / f"attempt-{attempt}.stderr",
        completed.stderr.decode("utf-8", errors="replace"),
    )
    payload = {
        "attempt": attempt,
        "returncode": completed.returncode,
        "timed_out": completed.timed_out,
        "stdout_truncated": completed.stdout_truncated,
        "stderr_truncated": completed.stderr_truncated,
    }
    try:
        write_json_atomic(
            artifact_dir / f"attempt-{attempt}.diagnostics.json",
            payload,
            exclusive=True,
        )
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc
    # Terminal artifacts landed: drop the live sink unless the outcome
    # needs its tail (timeout, kill, or a write failure, which raises
    # above and retains the sink). Reference steps and live when present.
    prefix = f"attempt-{attempt}.command"
    if live_path is not None and not retain_live_sink(completed):
        cleanup_live_sink(live_path)
    logs = {
        "stdout": f"attempt-{attempt}.stdout",
        "stderr": f"attempt-{attempt}.stderr",
    }
    if live_path is not None and Path(live_path).is_file():
        logs["live"] = live_file_for(prefix)
    steps_ref = (
        steps_file_for(prefix)
        if steps_path is not None and Path(steps_path).is_file()
        else None
    )
    active = recorder or OperationRecorder.for_context(context, instance.instance_id)
    try:
        active.finish(
            "command",
            kind="subprocess",
            label=label,
            attempt=attempt,
            started_at=started_at,
            duration_seconds=completed.duration_seconds,
            argv=argv,
            returncode=completed.returncode,
            timed_out=completed.timed_out,
            stdout_truncated=completed.stdout_truncated,
            stderr_truncated=completed.stderr_truncated,
            logs=logs,
            steps=steps_ref,
        )
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc


def _write_exclusive_text(path: Path, text: str) -> None:
    try:
        write_text_artifact(path, text, exclusive=True)
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc


def _resolve_cwd(command_config: CommandFinalizerConfig) -> str:
    if command_config.cwd == "primary":
        return resolve_finalizer_project_dir()
    raise FinalizerExecutionError(f"unsupported cwd policy {command_config.cwd!r}")
