"""Bounded attempts, immutable evidence, and fail-closed aggregation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import pytest

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.bounded_subprocess import (
    STDOUT_CAP_BYTES,
    run_bounded_subprocess,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import _write_aggregate_result
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.ledger import (
    InstanceLedger,
    is_retryable_result,
    run_budgeted_attempts,
)
from sase.finalizers.providers import FinalizerProviderRecord


def _config(
    instances: dict[str, ConfiguredFinalizerInstance],
) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=tuple(instances),
        required=(),
        instances=instances,
        provenance={},
    )


def _instance(
    instance_id: str,
    provider_ref: str,
    *,
    config: dict[str, Any] | None = None,
    max_attempts: int = 1,
) -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id=instance_id,
        provider_ref=provider_ref,
        max_attempts=max_attempts,
        config=config or {},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def _command(
    tmp_path: Path,
    script: str,
    *,
    max_attempts: int = 1,
    timeout: str = "5s",
    instance_id: str = "local-check",
) -> tuple[ConfiguredFinalizerInstance, FinalizerConfig, FinalizerExecutionContext]:
    instance = _instance(
        instance_id,
        "builtin@command",
        max_attempts=max_attempts,
        config={
            "command": [sys.executable, "-c", script],
            "cwd": "primary",
            "timeout": timeout,
            "submission": "none",
        },
    )
    context = FinalizerExecutionContext(
        artifacts_dir=str(tmp_path),
        plan_digest="sha256:test",
    )
    return instance, _config({instance_id: instance}), context


def test_retryable_command_stops_at_budget_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    counter = tmp_path / "runs.txt"
    instance, _config_unused, context = _command(
        tmp_path,
        (
            "from pathlib import Path; "
            f"p=Path({str(counter)!r}); "
            "p.write_text(str(int(p.read_text() or 0)+1) if p.exists() else '1'); "
            "raise SystemExit(1)"
        ),
        max_attempts=2,
    )
    result = execute_non_commit_finalizer(
        instance, _config({"local-check": instance}), context
    )

    assert result.status == "failed"
    assert [item.attempt for item in result.attempts] == [1, 2]
    assert counter.read_text() == "2"
    assert (tmp_path / "finalizers" / "local-check" / "attempt-1.stdout").exists()
    assert (tmp_path / "finalizers" / "local-check" / "attempt-2.stdout").exists()


def test_command_timeout_is_terminal_even_with_remaining_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    instance, config, context = _command(
        tmp_path,
        "import time; time.sleep(2)",
        max_attempts=3,
        timeout="50ms",
    )
    result = execute_non_commit_finalizer(instance, config, context)

    assert result.status == "failed"
    assert result.attempts[0].diagnostic_code == "command_timeout"
    assert len(result.attempts) == 1
    assert not is_retryable_result(result)


def test_provider_authored_skipped_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance("audit", "example-finalizers@audit", max_attempts=2)
    provider = FinalizerProviderRecord(
        provider_ref="example-finalizers@audit",
        provider_id="audit",
        package="example-finalizers",
        version="1.0.0",
        entry_point="example_finalizers:provider",
        builtin=False,
    )
    monkeypatch.setattr(
        "sase.finalizers.executor.collect_finalizer_providers",
        lambda: (provider,),
    )
    calls: list[str] = []

    def run_operation(
        _instance: ConfiguredFinalizerInstance,
        _provider: FinalizerProviderRecord,
        operation: str,
        _request: Mapping[str, Any],
        _context: FinalizerExecutionContext,
    ) -> dict[str, Any]:
        calls.append(operation)
        return {
            "schema_version": 1,
            "operation": operation,
            "provider_ref": "example-finalizers@audit",
            "instance_id": "audit",
            "status": "skipped" if operation == "execute" else "ok",
        }

    result = execute_non_commit_finalizer(
        instance,
        _config({"audit": instance}),
        FinalizerExecutionContext(artifacts_dir=str(tmp_path), plan_digest="sha256:t"),
        operation_runner=run_operation,
    )

    assert result.status == "failed"
    assert result.attempts[0].diagnostic_code == "provider_skipped_forbidden"
    assert "execute" in calls
    assert not is_retryable_result(result)


def test_retryable_plugin_execute_stops_at_budget_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance("audit", "example-finalizers@audit", max_attempts=2)
    provider = FinalizerProviderRecord(
        provider_ref="example-finalizers@audit",
        provider_id="audit",
        package="example-finalizers",
        version="1.0.0",
        entry_point="example_finalizers:provider",
        builtin=False,
    )
    monkeypatch.setattr(
        "sase.finalizers.executor.collect_finalizer_providers",
        lambda: (provider,),
    )
    executes = {"count": 0}

    def run_operation(
        _instance: ConfiguredFinalizerInstance,
        _provider: FinalizerProviderRecord,
        operation: str,
        _request: Mapping[str, Any],
        _context: FinalizerExecutionContext,
    ) -> dict[str, Any]:
        if operation == "execute":
            executes["count"] += 1
            return {
                "schema_version": 1,
                "operation": operation,
                "provider_ref": "example-finalizers@audit",
                "instance_id": "audit",
                "status": "failed",
                "diagnostics": [
                    {
                        "code": "execute_failed",
                        "severity": "error",
                        "message": "boom",
                    }
                ],
            }
        return {
            "schema_version": 1,
            "operation": operation,
            "provider_ref": "example-finalizers@audit",
            "instance_id": "audit",
            "status": "ok",
        }

    result = execute_non_commit_finalizer(
        instance,
        _config({"audit": instance}),
        FinalizerExecutionContext(artifacts_dir=str(tmp_path), plan_digest="sha256:t"),
        operation_runner=run_operation,
    )

    assert result.status == "failed"
    assert executes["count"] == 2
    assert [item.attempt for item in result.attempts] == [1, 2]


def test_controller_failure_is_not_published_as_aggregate_success(
    tmp_path: Path,
) -> None:
    _write_aggregate_result(
        str(tmp_path),
        [
            FinalizerInstanceResultWire(instance_id="lint", status="skipped"),
            FinalizerInstanceResultWire(instance_id="audit", status="success"),
        ],
        "failed",
        cycles=3,
    )
    payload = json.loads((tmp_path / "finalizer_result.json").read_text())
    assert payload["status"] == "failed"
    assert payload["diagnostics"][0]["code"] == "controller_failed"


def test_reactivation_does_not_exceed_host_attempt_budget() -> None:
    ledger = InstanceLedger("commit", max_attempts=1)
    ledger.consume_before_execute()
    calls = {"n": 0}

    def run_once() -> FinalizerInstanceResultWire:
        calls["n"] += 1
        return FinalizerInstanceResultWire(instance_id="commit", status="success")

    result = run_budgeted_attempts(ledger, run_once)
    assert calls["n"] == 0
    assert result.status == "failed"
    assert result.attempts[-1].diagnostic_code == "attempt_budget_exhausted"


def test_ledger_merges_evidence_across_attempts() -> None:
    ledger = InstanceLedger("lint", max_attempts=2)
    first = FinalizerInstanceResultWire(
        instance_id="lint",
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=1,
                status="failed",
                diagnostic_code="command_failed",
            )
        ],
        evidence=[FinalizerOutcomeEvidenceWire(kind="exit_code", value="1")],
        diagnostics=[
            FinalizerDiagnosticWire(
                code="command_failed",
                message="fail",
                severity="error",
                instance_id="lint",
                attempt=1,
            )
        ],
    )
    ledger.record(first)
    second = FinalizerInstanceResultWire(
        instance_id="lint",
        status="success",
        attempts=[FinalizerAttemptWire(attempt=2, status="success")],
        evidence=[FinalizerOutcomeEvidenceWire(kind="exit_code", value="0")],
    )
    merged = ledger.record(second)
    assert [item.value for item in merged.evidence] == ["1", "0"]
    assert [item.attempt for item in merged.attempts] == [1, 2]
    assert merged.diagnostics[0].attempt == 1


def test_oversized_stdout_fails_closed_and_kills_the_process() -> None:
    completed = run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * 2_000_000); sys.stdout.flush(); import time; time.sleep(30)",
        ],
        cwd=".",
        env=dict(os.environ),
        input_bytes=None,
        timeout=5,
        stdout_cap=64_000,
    )
    assert completed.stdout_truncated
    assert len(completed.stdout) <= 64_000
    assert completed.returncode != 0


def test_simultaneous_stdout_and_stderr_pressure_is_bounded() -> None:
    script = "\n".join(
        [
            "import sys, threading, time",
            "def spew(stream):",
            "    stream.write(b'y' * 2_000_000)",
            "    stream.flush()",
            "threading.Thread(target=spew, args=(sys.stdout.buffer,), daemon=True).start()",
            "spew(sys.stderr.buffer)",
            "time.sleep(30)",
        ]
    )
    completed = run_bounded_subprocess(
        [sys.executable, "-c", script],
        cwd=".",
        env=dict(os.environ),
        input_bytes=None,
        timeout=5,
        stdout_cap=32_000,
        stderr_cap=32_000,
    )
    assert completed.stdout_truncated or completed.stderr_truncated
    assert len(completed.stdout) <= 32_000
    assert len(completed.stderr) <= 32_000


def test_timeout_kills_descendant_processes(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = "\n".join(
        [
            "import os, time, pathlib",
            f"p = pathlib.Path({str(child_pid_file)!r})",
            "child = os.fork()",
            "if child == 0:",
            "    p.write_text(str(os.getpid()))",
            "    time.sleep(60)",
            "else:",
            "    time.sleep(60)",
        ]
    )
    started = time.monotonic()
    completed = run_bounded_subprocess(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=0.2,
    )
    assert completed.timed_out
    assert time.monotonic() - started < 5
    time.sleep(0.2)  # sase-test-wait: reap killed descendant before pid probe
    if child_pid_file.exists():
        child_pid = int(child_pid_file.read_text().strip() or "0")
        if child_pid:
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)


def test_command_output_cap_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    instance, config, context = _command(
        tmp_path,
        "import sys; sys.stdout.write('x'*2000000)",
        max_attempts=3,
        timeout="5s",
    )
    result = execute_non_commit_finalizer(instance, config, context)
    assert result.status == "failed"
    assert result.attempts[0].diagnostic_code == "command_output_cap"
    assert len(result.attempts) == 1
    stdout = tmp_path / "finalizers" / "local-check" / "attempt-1.stdout"
    assert stdout.exists()
    assert stdout.stat().st_size <= STDOUT_CAP_BYTES + 16
