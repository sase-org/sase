"""Bounded execution of the configured after-rebase gate hook.

Phase ``gate-runner`` of the rebased-stitch gate epic: take a pending gate
context, load project-scoped configuration for its explicit repository,
launch the configured command with one hard monotonic deadline, and classify
the collected facts through the shared Rust policy facade
(:mod:`sase.core.rebase_gate`).

Contract (owned by Rust; this module only supplies IO facts):

- Disabled or invalid gate settings never launch a process. An empty
  ``commit_hooks.after_rebase`` command returns the facade's ``skip`` verdict.
- The command runs with repository-root cwd and two environment variables:
  ``SASE_REBASE_CONTEXT`` names a temporary JSON input file holding the
  pending context, and ``SASE_REBASE_RESULT`` names the fresh result file the
  checker writes. Changed paths are never interpolated into shell text.
- One monotonic wall-clock budget covers context preparation, command
  execution, teardown, and result reads. The group is terminated on timeout
  and killed after a short bounded grace period, then reaped; drain threads
  join with a bounded wait so a descendant holding a pipe open cannot hang
  the finalizer.
- Every gate error fails open: timeout, signal, spawn failure, unsupported
  exits, malformed/missing/stale reports, invalid config, explicit ``error``
  reports, and observability/cleanup failures produce a visible warning and
  allow the push. Only a valid matching ``findings`` report blocks it.
- Cancellation of the overall stitch stays cancellation: ``KeyboardInterrupt``
  and task cancellation terminate the subprocess group best-effort and are
  re-raised, never converted into permission to push.

Python builds a ``warn`` decision directly only for inputs the Rust wire
types cannot represent (a non-string hook command, an unusable timeout, an
unloadable config layer) or when the facade itself raises. Every verdict
that depends on execution evidence comes from the facade.

This module never wires publication or dispatch and never enables the repo
hook; it only executes one gate context on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Literal, cast

from sase.config.core import load_merged_config_for_local_path
from sase.core.rebase_gate import (
    REBASE_GATE_WIRE_SCHEMA_VERSION,
    CommandFactsWire,
    ConfigWire,
    ContextWire,
    DecisionWire,
    ReportWire,
)
from sase.output import print_status
from sase.workflows.commit.hook_utils import (
    HOOK_READER_JOIN_SECONDS,
    decode_tail,
    drain_stream,
    hook_log_root,
    normalize_path,
    repo_digest,
    write_json_atomic,
)

REBASE_GATE_CONTEXT_ENV = "SASE_REBASE_CONTEXT"
REBASE_GATE_RESULT_ENV = "SASE_REBASE_RESULT"

GATE_PHASE_LABEL = "after_rebase"

_DEFAULT_TIMEOUT_SECONDS = 10.0
_INVALID_TIMEOUT_SENTINEL = -1.0
_RESULT_CAP_BYTES = 1_048_576
_KILL_GRACE_SECONDS = 1.0

GateStepState = Literal["start", "ok", "fail"]

__all__ = [
    "GATE_PHASE_LABEL",
    "REBASE_GATE_CONTEXT_ENV",
    "REBASE_GATE_RESULT_ENV",
    "RebaseGateOutcome",
    "run_after_rebase_gate",
]


@dataclass(frozen=True)
class RebaseGateOutcome:
    """One executed gate attempt: the facade verdict plus evidence."""

    decision: DecisionWire
    duration_seconds: float
    metadata_path: Path | None
    stdout_tail: str
    stderr_tail: str


def run_after_rebase_gate(
    context: ContextWire,
    repo_root: str,
) -> RebaseGateOutcome:
    """Execute the configured after-rebase hook for *context*.

    Loads ``commit_hooks`` for the explicit *repo_root* project layer (even
    when the host cwd belongs to another project), runs the command under
    the shared deadline, and returns the facade's verdict. Never raises for
    gate errors; cancellation is re-raised.
    """
    started = time.monotonic()
    root = normalize_path(repo_root)
    if not isinstance(context, dict):
        return _warn_without_evidence(
            started,
            "invalid pending rebase context; gate skipped",
            f"expected a context object, got {type(context).__name__}",
        )

    try:
        config = load_merged_config_for_local_path(Path(root))
    except Exception as exc:  # noqa: BLE001 - config failure fails open
        return _warn_without_evidence(
            started,
            "could not load project configuration; rebase gate skipped",
            str(exc),
        )

    hooks = config.get("commit_hooks", {})
    if not isinstance(hooks, dict):
        return _warn_without_evidence(
            started,
            "invalid commit_hooks configuration; rebase gate skipped",
            f"expected an object, got {type(hooks).__name__}",
        )
    hook_raw = hooks.get("after_rebase", "")
    if not isinstance(hook_raw, str):
        return _warn_without_evidence(
            started,
            "invalid commit_hooks.after_rebase; rebase gate skipped",
            f"expected a string, got {hook_raw!r}",
        )
    hook = hook_raw.strip()
    timeout_raw = hooks.get("after_rebase_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    timeout = _normalize_timeout(timeout_raw)

    if not hook:
        return _classify_disabled(context, started, timeout_raw)
    if timeout is None:
        return _warn_without_evidence(
            started,
            "invalid commit_hooks.after_rebase_timeout_seconds; rebase gate skipped",
            f"expected positive finite seconds at most 30, got {timeout_raw!r}",
        )
    return _execute_gate(context, root, hook, timeout, started)


def _normalize_timeout(value: Any) -> float | None:
    """Return *value* as seconds, or None when it is missing/unusable."""
    if value is None:
        return _DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _warn_decision(reason: str, diagnostics: str | None) -> DecisionWire:
    """Build a fail-open warning for inputs the wire cannot represent."""
    return {
        "schema_version": REBASE_GATE_WIRE_SCHEMA_VERSION,
        "verdict": "warn",
        "reason": reason,
        "findings": [],
        "diagnostics": diagnostics,
    }


def _warn_without_evidence(
    started: float,
    reason: str,
    diagnostics: str | None,
) -> RebaseGateOutcome:
    """Fail open before any evidence directory exists."""
    decision = _warn_decision(reason, diagnostics)
    print_status(f"Rebase gate: {reason}.", "warning")
    if diagnostics:
        print_status(f"Rebase gate detail: {diagnostics}", "warning")
    return RebaseGateOutcome(
        decision=decision,
        duration_seconds=time.monotonic() - started,
        metadata_path=None,
        stdout_tail="",
        stderr_tail="",
    )


def _classify_disabled(
    context: ContextWire,
    started: float,
    timeout_raw: Any,
) -> RebaseGateOutcome:
    """Return the facade's skip verdict without launching a process."""
    from sase.core.rebase_gate import classify_rebase_gate_result

    timeout = _normalize_timeout(timeout_raw)
    config: ConfigWire = {
        "hook_command": "",
        "timeout_seconds": (
            timeout if timeout is not None else _INVALID_TIMEOUT_SENTINEL
        ),
    }
    try:
        decision = classify_rebase_gate_result(context, config, {}, None)
    except Exception as exc:  # noqa: BLE001 - facade failure fails open
        return _warn_without_evidence(
            started,
            "rebase gate policy unavailable; gate skipped",
            str(exc),
        )
    return RebaseGateOutcome(
        decision=decision,
        duration_seconds=time.monotonic() - started,
        metadata_path=None,
        stdout_tail="",
        stderr_tail="",
    )


def _emit_gate_step(
    cmd: str, *, state: GateStepState, detail: str | None = None
) -> None:
    """Emit a gate step on the finalizer step channel; never raises."""
    try:
        from sase.finalizers.steps import emit_step

        emit_step(f"{GATE_PHASE_LABEL} gate: {cmd}", state=state, detail=detail)
    except Exception:  # noqa: BLE001 - observability is best-effort
        pass


def _execute_gate(
    context: ContextWire,
    root: str,
    hook: str,
    timeout: float,
    started: float,
) -> RebaseGateOutcome:
    """Run *hook* under the shared deadline and classify the outcome."""
    from sase.core.rebase_gate import classify_rebase_gate_result

    deadline = started + timeout
    changed_paths = context.get("changed_paths", [])
    changed_count = len(changed_paths) if isinstance(changed_paths, list) else 0

    try:
        evidence_root = hook_log_root()
        evidence_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _warn_without_evidence(
            started,
            "could not create rebase gate evidence; gate skipped",
            str(exc),
        )
    stem = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')}"
        f".{GATE_PHASE_LABEL}.{repo_digest(root)}"
        f".{os.getpid()}.{uuid.uuid4().hex[:8]}"
    )
    metadata_path = evidence_root / f"{stem}.json"
    stdout_path = evidence_root / f"{stem}.stdout.log"
    stderr_path = evidence_root / f"{stem}.stderr.log"
    stdout_tail_path = evidence_root / f"{stem}.stdout.tail"
    stderr_tail_path = evidence_root / f"{stem}.stderr.tail"
    metadata: dict[str, object] = {
        "schema_version": 1,
        "kind": "after_rebase_gate",
        "status": "starting",
        "command": hook,
        "repo_root": root,
        "timeout_seconds": timeout,
        "inputs": context.get("inputs", []),
        "current_head": context.get("current_head", ""),
        "current_tree": context.get("current_tree", ""),
        "changed_path_count": changed_count,
        "start_time": datetime.now(UTC).isoformat(),
        "start_time_epoch": time.time(),
        "paths": {
            "metadata": str(metadata_path),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "stdout_tail": str(stdout_tail_path),
            "stderr_tail": str(stderr_tail_path),
        },
    }
    try:
        write_json_atomic(metadata_path, metadata)
        for path in (
            stdout_path,
            stderr_path,
            stdout_tail_path,
            stderr_tail_path,
        ):
            path.touch(exist_ok=False)
    except OSError as exc:
        return _warn_without_evidence(
            started,
            "could not create rebase gate evidence; gate skipped",
            str(exc),
        )
    print_status(f"After-rebase gate evidence: {metadata_path}", "info")
    print_status(f"Running after-rebase gate: {hook}", "progress")
    _emit_gate_step(hook, state="start", detail=hook)

    try:
        workdir = Path(tempfile.mkdtemp(prefix="sase-rebase-gate-"))
    except OSError as exc:
        return _fail_open_with_evidence(
            started,
            metadata_path,
            metadata,
            hook,
            "could not create rebase gate input; gate skipped",
            str(exc),
        )
    context_path = workdir / "context.json"
    result_path = workdir / "result.json"
    try:
        context_path.write_text(
            json.dumps(dict(context), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _cleanup_workdir(workdir)
        return _fail_open_with_evidence(
            started,
            metadata_path,
            metadata,
            hook,
            "could not write rebase gate context; gate skipped",
            str(exc),
        )

    metadata.update({"status": "running"})
    _write_json_best_effort(metadata_path, metadata)

    facts, stdout_tail, stderr_tail = _run_gate_command(
        hook,
        repo_root=root,
        context_path=context_path,
        result_path=result_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_tail_path=stdout_tail_path,
        stderr_tail_path=stderr_tail_path,
        deadline=deadline,
        metadata=metadata,
        metadata_path=metadata_path,
    )
    report = _read_gate_report(result_path)

    try:
        decision = classify_rebase_gate_result(
            context,
            {"hook_command": hook, "timeout_seconds": timeout},
            facts,
            report,
        )
    except Exception as exc:  # noqa: BLE001 - facade failure fails open
        _cleanup_workdir(workdir)
        return _fail_open_with_evidence(
            started,
            metadata_path,
            metadata,
            hook,
            "rebase gate policy unavailable; gate skipped",
            str(exc),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    duration = time.monotonic() - started
    metadata.update(
        {
            "status": "decided",
            "verdict": decision.get("verdict", ""),
            "reason": decision.get("reason", ""),
            "findings": decision.get("findings", []),
            "diagnostics": decision.get("diagnostics"),
            "command": dict(facts),
            "duration_seconds": duration,
            "end_time": datetime.now(UTC).isoformat(),
        }
    )
    _write_json_best_effort(metadata_path, metadata)
    _cleanup_workdir(workdir)
    _report_decision(hook, decision, metadata_path)
    _emit_gate_step(
        hook,
        state="ok" if decision.get("verdict") in ("skip", "pass") else "fail",
        detail=str(decision.get("reason", "")),
    )
    return RebaseGateOutcome(
        decision=decision,
        duration_seconds=duration,
        metadata_path=metadata_path,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def _run_gate_command(
    cmd: str,
    *,
    repo_root: str,
    context_path: Path,
    result_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    stdout_tail_path: Path,
    stderr_tail_path: Path,
    deadline: float,
    metadata: dict[str, object],
    metadata_path: Path,
) -> tuple[CommandFactsWire, str, str]:
    """Launch *cmd* and wait up to *deadline*; always reaps the process.

    Returns command facts plus the captured output tails. Cancellation
    terminates the subprocess group best-effort and is re-raised.
    """
    env = dict(os.environ)
    env[REBASE_GATE_CONTEXT_ENV] = str(context_path)
    env[REBASE_GATE_RESULT_ENV] = str(result_path)
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            cwd=repo_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    except OSError as exc:
        metadata.update({"status": "failed_to_start", "error": str(exc)})
        _write_json_best_effort(metadata_path, metadata)
        return (
            {"timed_out": False, "spawn_error": str(exc)},
            "",
            str(exc),
        )

    metadata.update({"status": "running", "pid": process.pid})
    _write_json_best_effort(metadata_path, metadata)

    lock = threading.Lock()
    written = {"stdout": 0, "stderr": 0}
    truncated = {"stdout": False, "stderr": False}
    tails: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    threads = [
        threading.Thread(
            target=drain_stream,
            args=(
                process.stdout,
                "stdout",
                stdout_path,
                stdout_tail_path,
                lock,
                written,
                truncated,
                tails,
            ),
            daemon=True,
        ),
        threading.Thread(
            target=drain_stream,
            args=(
                process.stderr,
                "stderr",
                stderr_path,
                stderr_tail_path,
                lock,
                written,
                truncated,
                tails,
            ),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    try:
        exit_code, timed_out, term_signal = _wait_gate_process(process, deadline)
    except BaseException:
        _terminate_group(process)
        _close_pipes(process)
        raise
    for thread in threads:
        thread.join(timeout=HOOK_READER_JOIN_SECONDS)
    _close_pipes(process)

    with lock:
        stdout_tail = decode_tail(tails["stdout"])
        stderr_tail = decode_tail(tails["stderr"])
        stdout_truncated = truncated["stdout"]
        stderr_truncated = truncated["stderr"]
    facts: CommandFactsWire = {"timed_out": timed_out}
    if term_signal is not None:
        facts["signal"] = term_signal
    else:
        facts["exit_code"] = exit_code
    metadata.update(
        {
            "status": "timeout" if timed_out else "finished",
            "returncode": exit_code,
            "signal": term_signal,
            "timed_out": timed_out,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
    )
    _write_json_best_effort(metadata_path, metadata)
    return facts, stdout_tail, stderr_tail


def _wait_gate_process(
    process: subprocess.Popen[bytes],
    deadline: float,
) -> tuple[int | None, bool, int | None]:
    """Wait for *process* up to *deadline*; kill the group on timeout.

    Returns ``(exit_code, timed_out, signal)``. A returncode below zero is
    reported as a signal with no exit code.
    """
    remaining = deadline - time.monotonic()
    try:
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, remaining)
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        _terminate_group(process)
        try:
            returncode = process.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_group(process, kill=True)
            try:
                returncode = process.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                return None, True, None
        return _split_returncode(returncode, timed_out=True)
    return _split_returncode(returncode, timed_out=False)


def _split_returncode(
    returncode: int, *, timed_out: bool
) -> tuple[int | None, bool, int | None]:
    if returncode < 0:
        return None, timed_out, -returncode
    return returncode, timed_out, None


def _terminate_group(process: subprocess.Popen[bytes], *, kill: bool = False) -> None:
    """Signal the subprocess group; never raises."""
    try:
        sig = signal.SIGKILL if kill else signal.SIGTERM
        os.killpg(process.pid, sig)
    except (OSError, AttributeError, ValueError):
        try:
            if kill:
                process.kill()
            else:
                process.terminate()
        except (OSError, ValueError):
            pass


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    """Close captured pipes so stray readers unblock; never raises."""
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _read_gate_report(result_path: Path) -> ReportWire | None:
    """Read the checker's result report; None when missing/unusable.

    The report is untrusted checker output: size-bounded here, validated by
    the Rust policy. Anything unusable maps to a fail-open warning there.
    """
    try:
        if not result_path.is_file():
            return None
        if result_path.stat().st_size > _RESULT_CAP_BYTES:
            return None
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast("ReportWire", raw)


def _fail_open_with_evidence(
    started: float,
    metadata_path: Path,
    metadata: dict[str, object],
    hook: str,
    reason: str,
    diagnostics: str | None,
    *,
    stdout_tail: str = "",
    stderr_tail: str = "",
) -> RebaseGateOutcome:
    """Fail open after evidence exists; records the warning there."""
    decision = _warn_decision(reason, diagnostics)
    metadata.update(
        {
            "status": "warned",
            "verdict": "warn",
            "reason": reason,
            "diagnostics": diagnostics,
            "duration_seconds": time.monotonic() - started,
            "end_time": datetime.now(UTC).isoformat(),
        }
    )
    _write_json_best_effort(metadata_path, metadata)
    _report_decision(hook, decision, metadata_path)
    _emit_gate_step(hook, state="fail", detail=reason)
    return RebaseGateOutcome(
        decision=decision,
        duration_seconds=time.monotonic() - started,
        metadata_path=metadata_path,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def _write_json_best_effort(path: Path, payload: dict[str, object]) -> None:
    """Write evidence JSON; observability failures never raise."""
    try:
        write_json_atomic(path, payload)
    except OSError:
        pass


def _cleanup_workdir(workdir: Path) -> None:
    """Remove transient gate files; cleanup failures fail open."""
    try:
        shutil.rmtree(workdir, ignore_errors=False)
    except OSError as exc:
        print_status(
            f"Rebase gate: could not remove temporary directory {workdir}: {exc}",
            "warning",
        )


def _report_decision(
    hook: str, decision: DecisionWire, metadata_path: Path | None
) -> None:
    """Print the visible gate outcome; never raises."""
    try:
        verdict = decision.get("verdict", "")
        reason = decision.get("reason", "")
        if verdict == "warn":
            print_status(f"Rebase gate warning: {reason}", "warning")
            diagnostics = decision.get("diagnostics")
            if diagnostics:
                print_status(f"Rebase gate detail: {diagnostics}", "warning")
        elif verdict == "block":
            findings = decision.get("findings", [])
            count = len(findings) if isinstance(findings, list) else 0
            print_status(
                f"Rebase gate blocked the push: {reason} ({count} finding(s))",
                "error",
            )
        if metadata_path is not None:
            print_status(f"After-rebase gate evidence: {metadata_path}", "info")
    except Exception:  # noqa: BLE001 - observability is best-effort
        pass
