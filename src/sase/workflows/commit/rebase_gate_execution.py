"""Bounded execution of one after-rebase gate attempt."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sase.core.rebase_gate import (
    CommandFactsWire,
    ContextWire,
    DecisionWire,
    ReportWire,
)
from sase.output import print_status
from sase.workflows.commit._rebase_gate_common import (
    GATE_PHASE_LABEL,
    RebaseGateOutcome,
    warn_decision,
    warn_without_evidence,
    write_json_best_effort,
)
from sase.workflows.commit.hook_utils import (
    hook_log_root,
    repo_digest,
    write_json_atomic,
)
from sase.workflows.commit.rebase_gate_budget import (
    GateBudgetExhausted,
    GateWorkBudget,
)
from sase.workflows.commit.rebase_gate_process import run_gate_command

_RESULT_CAP_BYTES = 1_048_576

GateStepState = Literal["start", "ok", "fail"]


def execute_gate(
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
        return warn_without_evidence(
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
        return warn_without_evidence(
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
        write_json_best_effort(metadata_path, metadata)

        facts, stdout_tail, stderr_tail = run_gate_command(
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
        decision = warn_decision(*warning)
    if decision is None:
        decision = warn_decision(
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
    write_json_best_effort(metadata_path, metadata)
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


def _emit_gate_step(
    cmd: str, *, state: GateStepState, detail: str | None = None
) -> None:
    """Emit a gate step on the finalizer step channel; never raises."""
    try:
        from sase.finalizers.steps import emit_step

        emit_step(f"{GATE_PHASE_LABEL} gate: {cmd}", state=state, detail=detail)
    except Exception:  # noqa: BLE001 - observability is best-effort
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
