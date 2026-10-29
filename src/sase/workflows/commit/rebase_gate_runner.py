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
from dataclasses import dataclass
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
from sase.workflows.commit.rebase_gate_budget import (
    GateBudgetExhausted,
    GateWorkBudget,
)
from sase.output import print_status
from sase.workflows.commit.hook_utils import (
    decode_tail,
    drain_stream,
    hook_log_root,
    local_config_path_for_repo_root,
    normalize_path,
    repo_digest,
    write_json_atomic,
)

REBASE_GATE_CONTEXT_ENV = "SASE_REBASE_CONTEXT"
REBASE_GATE_RESULT_ENV = "SASE_REBASE_RESULT"

GATE_PHASE_LABEL = "after_rebase"

_DEFAULT_TIMEOUT_SECONDS = 10.0
_RESULT_CAP_BYTES = 1_048_576
_KILL_GRACE_SECONDS = 0.1
_INHERITED_PIPE_PROBE_SECONDS = 0.05

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


@dataclass(frozen=True)
class GateSettings:
    """Project-local command settings after Rust timeout preflight."""

    hook_command: str
    timeout_seconds: float


def run_after_rebase_gate(
    context: ContextWire,
    repo_root: str,
    *,
    budget: GateWorkBudget | None = None,
    settings: GateSettings | None = None,
) -> RebaseGateOutcome:
    """Execute the configured after-rebase hook for *context*.

    Loads ``commit_hooks`` for the explicit *repo_root* project layer (even
    when the host cwd belongs to another project), runs the command under
    the shared deadline, and returns the facade's verdict. Never raises for
    gate errors; cancellation is re-raised.
    """
    started = time.monotonic()
    budget = budget or GateWorkBudget()
    root = normalize_path(repo_root)
    if not isinstance(context, dict):
        return _warn_without_evidence(
            started,
            "invalid pending rebase context; gate skipped",
            f"expected a context object, got {type(context).__name__}",
        )

    warning: tuple[str, str | None] | None = None
    if settings is None:
        settings, warning = load_after_rebase_gate_settings(root, budget)
    if warning is not None:
        reason, diagnostics = warning
        return _warn_without_evidence(
            started,
            reason,
            diagnostics,
        )
    if settings is None:
        return _warn_without_evidence(
            started,
            "could not validate project configuration; rebase gate skipped",
            None,
        )
    if not settings.hook_command:
        return _classify_disabled(context, started, settings.timeout_seconds)
    return _execute_gate(
        context,
        root,
        settings.hook_command,
        settings.timeout_seconds,
        started,
        budget,
    )


def load_after_rebase_gate_settings(
    repo_root: str,
    budget: GateWorkBudget,
) -> tuple[GateSettings | None, tuple[str, str | None] | None]:
    """Load project settings and validate numeric policy through Rust.

    Returns a visible warning tuple for invalid settings. Empty hooks are
    represented as disabled settings and do not trigger gate-context work.
    """
    root = normalize_path(repo_root)
    try:
        with budget.measure():
            config = load_merged_config_for_local_path(
                local_config_path_for_repo_root(root)
            )
    except GateBudgetExhausted:
        return None, (
            "rebase gate budget expired while loading project configuration",
            None,
        )
    except Exception as exc:  # noqa: BLE001 - config failure fails open
        return None, (
            "could not load project configuration; rebase gate skipped",
            str(exc),
        )

    hooks = config.get("commit_hooks", {})
    if not isinstance(hooks, dict):
        return None, (
            "invalid commit_hooks configuration; rebase gate skipped",
            f"expected an object, got {type(hooks).__name__}",
        )
    hook_raw = hooks.get("after_rebase", "")
    if not isinstance(hook_raw, str):
        return None, (
            "invalid commit_hooks.after_rebase; rebase gate skipped",
            f"expected a string, got {hook_raw!r}",
        )
    hook = hook_raw.strip()
    timeout_raw = hooks.get("after_rebase_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    timeout = _normalize_timeout(timeout_raw)
    if timeout is None:
        return None, (
            "invalid commit_hooks.after_rebase_timeout_seconds; rebase gate skipped",
            f"expected a numeric timeout, got {timeout_raw!r}",
        )
    try:
        with budget.measure():
            from sase.core.rebase_gate import (
                validate_rebase_gate_timeout_seconds,
            )

            timeout = validate_rebase_gate_timeout_seconds(timeout)
    except GateBudgetExhausted:
        return None, (
            "rebase gate budget expired while validating configuration",
            None,
        )
    except ValueError as exc:
        return None, (
            "invalid commit_hooks.after_rebase_timeout_seconds; rebase gate skipped",
            str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - missing binding fails open
        return None, (
            "rebase gate configuration policy unavailable; gate skipped",
            str(exc),
        )
    budget.set_timeout(timeout)
    if not hook:
        return GateSettings("", timeout), None
    return GateSettings(hook, timeout), None


def _normalize_timeout(value: Any) -> float | None:
    """Convert a numeric configuration value; Rust owns all numeric bounds."""
    if value is None:
        return _DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except OverflowError:
            return None
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
    timeout: float,
) -> RebaseGateOutcome:
    """Return the facade's skip verdict without launching a process."""
    from sase.core.rebase_gate import classify_rebase_gate_result

    config: ConfigWire = {
        "hook_command": "",
        "timeout_seconds": timeout,
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
    budget: GateWorkBudget,
) -> RebaseGateOutcome:
    """Run *hook* under the remaining shared budget and classify the result."""
    from sase.core.rebase_gate import classify_rebase_gate_result

    changed_paths = context.get("changed_paths", [])
    changed_count = len(changed_paths) if isinstance(changed_paths, list) else 0

    try:
        with budget.measure():
            evidence_root = hook_log_root()
            evidence_root.mkdir(parents=True, exist_ok=True)
    except (OSError, GateBudgetExhausted) as exc:
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

    workdir: Path | None = None
    result_path: Path | None = None
    facts: CommandFactsWire = {"timed_out": False}
    stdout_tail = ""
    stderr_tail = ""
    decision: DecisionWire | None = None
    warning: tuple[str, str | None] | None = None
    try:
        with budget.measure():
            workdir = Path(tempfile.mkdtemp(prefix="sase-rebase-gate-"))
            context_path = workdir / "context.json"
            result_path = workdir / "result.json"
            context_path.write_text(
                json.dumps(dict(context), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
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
            budget=budget,
            metadata=metadata,
            metadata_path=metadata_path,
        )

        report = None
        if result_path is not None and budget.work_remaining > 0:
            try:
                with budget.measure():
                    report = _read_gate_report(result_path)
            except GateBudgetExhausted:
                report = None

        decision = classify_rebase_gate_result(
            context,
            {"hook_command": hook, "timeout_seconds": timeout},
            facts,
            report,
        )
    except Exception as exc:  # noqa: BLE001 - facade failure fails open
        warning = (
            "rebase gate work failed; allowing publication",
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if workdir is not None:
            _cleanup_workdir(workdir, budget)

    duration = budget.spent_seconds
    if warning is not None:
        decision = _warn_decision(*warning)
    if decision is None:
        decision = _warn_decision(
            "rebase gate did not produce a decision; allowing publication", None
        )
    metadata.update(
        {
            "status": "warned" if decision.get("verdict") == "warn" else "decided",
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
    budget: GateWorkBudget,
    metadata: dict[str, object],
    metadata_path: Path,
) -> tuple[CommandFactsWire, str, str]:
    """Launch *cmd* within the remaining budget and always reap its group.

    Returns command facts plus the captured output tails. Cancellation
    terminates and reaps the subprocess group best-effort, then propagates.
    """
    remaining = budget.work_remaining
    if remaining <= 0:
        return {"timed_out": True}, "", ""
    command_started = budget.clock()
    deadline = time.monotonic() + remaining
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
        budget.charge_elapsed(command_started)
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
    timed_out = False
    term_signal: int | None = None
    teardown_deadline = deadline + budget.teardown_remaining
    try:
        for thread in threads:
            thread.start()
        exit_code, timed_out, term_signal = _wait_gate_process(
            process, deadline, budget
        )
        pipe_deadline = min(
            deadline,
            time.monotonic() + _INHERITED_PIPE_PROBE_SECONDS,
        )
        for thread in threads:
            thread.join(timeout=max(0.0, pipe_deadline - time.monotonic()))
        descendants = _process_group_exists(process.pid)
        readers_alive = any(thread.is_alive() for thread in threads)
        if not timed_out and (descendants or readers_alive):
            _terminate_and_reap_group(process, budget)
            timed_out = True
        _close_pipes(process)
        for thread in threads:
            thread.join(timeout=max(0.0, teardown_deadline - time.monotonic()))
    except BaseException:
        _terminate_and_reap_group(process, budget)
        _close_pipes(process)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=min(0.05, budget.teardown_remaining))
        budget.charge_elapsed(command_started)
        raise
    budget.charge_elapsed(command_started)

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
    budget: GateWorkBudget,
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
        grace = min(_KILL_GRACE_SECONDS, budget.teardown_remaining / 2)
        _terminate_group(process)
        grace_end = time.monotonic() + grace
        _wait_group_until(process.pid, grace_end)
        _terminate_group(process, kill=True)
        try:
            returncode = process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return None, True, None
        if returncode is None:
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


def _process_group_exists(group_id: int) -> bool:
    """Return whether a hook process group still has any members."""
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, AttributeError, ValueError):
        return False
    return True


def _wait_group_until(group_id: int, deadline: float) -> None:
    """Give TERM-handling descendants a brief bounded chance to exit."""
    while time.monotonic() < deadline and _process_group_exists(group_id):
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _terminate_and_reap_group(
    process: subprocess.Popen[bytes], budget: GateWorkBudget
) -> None:
    """Terminate descendants even when the original group leader exited."""
    grace = min(_KILL_GRACE_SECONDS, budget.teardown_remaining / 2)
    _terminate_group(process)
    _wait_group_until(process.pid, time.monotonic() + grace)
    _terminate_group(process, kill=True)
    try:
        process.wait(timeout=grace)
    except (OSError, subprocess.TimeoutExpired):
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
        with result_path.open("rb") as stream:
            payload = stream.read(_RESULT_CAP_BYTES + 1)
        if len(payload) > _RESULT_CAP_BYTES:
            return None
        raw = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast("ReportWire", raw)


def _write_json_best_effort(path: Path, payload: dict[str, object]) -> None:
    """Write evidence JSON; observability failures never raise."""
    try:
        write_json_atomic(path, payload)
    except OSError:
        pass


def _cleanup_workdir(workdir: Path, budget: GateWorkBudget) -> None:
    """Remove transient gate files; cleanup failures fail open."""
    failures: list[OSError] = []

    def remove() -> None:
        try:
            shutil.rmtree(workdir, ignore_errors=False)
        except OSError as exc:
            failures.append(exc)

    worker = threading.Thread(target=remove, daemon=True)
    try:
        worker.start()
    except RuntimeError as exc:
        print_status(
            f"Rebase gate: could not start temporary directory cleanup for {workdir}: {exc}",
            "warning",
        )
        return
    try:
        with budget.measure(teardown=True):
            worker.join(timeout=budget.teardown_remaining)
    except GateBudgetExhausted:
        pass
    if worker.is_alive():
        print_status(
            f"Rebase gate: temporary directory cleanup exceeded its bounded allowance: {workdir}",
            "warning",
        )
    elif failures:
        cleanup_error = failures[0]
        print_status(
            f"Rebase gate: could not remove temporary directory {workdir}: {cleanup_error}",
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
