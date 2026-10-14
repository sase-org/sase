#!/usr/bin/env python3
"""Release watch state machine and verdict handling."""

from __future__ import annotations

import json
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _release_watch_api import (
    BAD_CONCLUSIONS,
    EXIT_CODES,
    GOOD_CONCLUSIONS,
    GH_TIMEOUT,
    PROCESS_TIMEOUT,
    SIGNALS,
    ReleasePullRequest,
    SignalFailure,
    Snapshot,
    WatchOptions,
    WatcherSignal,
    WorkflowRun,
    default_verdict_path,
    failed_excerpt,
    iso_utc,
    read_ci_watch_reason,
    run_process,
)


@dataclass
class ReleaseWatcher:
    options: WatchOptions
    reader: Any
    process: Callable[..., subprocess.CompletedProcess[str]] = run_process
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    output: Callable[[str], None] = print
    signal_module: Any = signal
    verdict_path: Path | None = None
    last_state_line: str = "no state read yet"
    state_history: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    last_dispatch: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    final_verdict: str | None = None
    final_detail: str = ""
    close_outcome: str = "not requested"
    last_snapshot: Snapshot | None = None
    received_signal: int | None = None
    _finalizing: bool = False
    _old_handlers: dict[int, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.verdict_path = (
            Path(self.options.verdict_file)
            if self.options.verdict_file
            else default_verdict_path()
        )

    def _install_signals(self) -> None:
        for name in ("SIGTERM", "SIGINT", "SIGHUP"):
            signum = getattr(self.signal_module, name, None)
            if signum is None:
                continue
            self._old_handlers[signum] = self.signal_module.getsignal(signum)
            self.signal_module.signal(signum, self._handle_signal)

    def _restore_signals(self) -> None:
        for signum, handler in self._old_handlers.items():
            self.signal_module.signal(signum, handler)
        self._old_handlers.clear()

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self.received_signal = signum
        if not self._finalizing:
            raise WatcherSignal(signum)

    def run(self) -> int:
        self._install_signals()
        try:
            try:
                self.reader.validate()
            except Exception as exc:
                self.set_verdict(
                    "WATCHER_BROKEN",
                    f"startup validation failed: {short_exception(exc)}",
                )
                return self.finalize()
            started = self.monotonic()
            deadline_at = started + self.options.deadline
            while True:
                if self.received_signal is not None:
                    self.set_verdict(
                        "DEADLINE",
                        f"signal {self.received_signal} arrived before a verdict",
                    )
                    break
                signal_values = self.reader.read_signals()
                failed = [
                    name
                    for name in SIGNALS
                    if isinstance(signal_values.get(name), SignalFailure)
                ]
                for name in SIGNALS:
                    if name in failed:
                        self.failures[name] = self.failures.get(name, 0) + 1
                    else:
                        self.failures[name] = 0
                line = self._render_state(signal_values, "reading")
                self.last_state_line = line
                self.state_history.append(line)
                if self.options.once:
                    if failed:
                        names = ", ".join(
                            f"{name} ({signal_values[name].message})" for name in failed
                        )
                        self.output(line)
                        self.set_verdict(
                            "WATCHER_BROKEN",
                            f"preflight did not parse required signal(s): {names}",
                        )
                        break
                    self._print_once(signal_values)
                    return 0
                broken = [name for name in failed if self.failures[name] >= 3]
                if broken:
                    details = "; ".join(
                        f"{name}: {signal_values[name].message}"
                        for name in broken
                        if isinstance(signal_values[name], SignalFailure)
                    )
                    line = self._render_state(signal_values, "verdict:WATCHER_BROKEN")
                    self.last_state_line = line
                    self.state_history[-1] = line
                    self.output(line)
                    self.set_verdict(
                        "WATCHER_BROKEN", f"three consecutive failed reads: {details}"
                    )
                    break
                if failed:
                    self.output(line)
                else:
                    snapshot = self._snapshot(signal_values)
                    self.last_snapshot = snapshot
                    verdict = self.evaluate(snapshot)
                    if verdict is not None:
                        line = self._render_state(
                            signal_values, f"verdict:{verdict[0]}"
                        )
                        self.last_state_line = line
                        self.state_history[-1] = line
                        self.output(line)
                        self.set_verdict(*verdict)
                        break
                    if self.monotonic() >= deadline_at:
                        line = self._render_state(signal_values, "verdict:DEADLINE")
                        self.last_state_line = line
                        self.state_history[-1] = line
                        self.output(line)
                        self.set_verdict("DEADLINE", self._deadline_detail(snapshot))
                        break
                    action_results = self.dispatch_due(snapshot)
                    line = self._render_state(
                        signal_values, ",".join(action_results) or "none"
                    )
                    self.last_state_line = line
                    self.state_history[-1] = line
                    self.output(line)
                if self.monotonic() >= deadline_at:
                    snapshot = self._snapshot(signal_values) if not failed else None
                    self.set_verdict("DEADLINE", self._deadline_detail(snapshot))
                    break
                self.sleep(
                    min(self.options.poll, max(0.0, deadline_at - self.monotonic()))
                )
        except WatcherSignal as exc:
            self.set_verdict(
                "DEADLINE", f"received signal {exc.signum}; last state retained"
            )
        except BaseException as exc:
            self.set_verdict(
                "WATCHER_BROKEN", short_exception(exc, include_traceback=True)
            )
        return self.finalize()

    def _render_state(self, values: Mapping[str, object], action: str) -> str:
        rendered: list[str] = []
        for name in SIGNALS:
            value = values.get(name)
            if isinstance(value, SignalFailure):
                item = "ERROR:" + value.message.replace(" ", "_")[:160]
            elif name == "pypi" and isinstance(value, tuple):
                item = "present" if self.options.version in value else "absent"
            elif name == "release_pr":
                item = (
                    "gone"
                    if value is None
                    else f"#{value.number}:{'merged' if value.is_merged else value.state.lower()}"
                )
            elif name == "full_ci" and isinstance(value, tuple):
                latest = max(value, key=lambda run: run.updated_at, default=None)
                item = (
                    f"in_flight:{sum(run.is_in_flight for run in value)}"
                    if any(run.is_in_flight for run in value)
                    else (
                        "none"
                        if latest is None
                        else f"{latest.run_id}:{latest.conclusion}:{latest.sha[:12]}"
                    )
                )
            elif name == "master_gate" and isinstance(value, tuple):
                sha, run = value
                item = (
                    f"{run.run_id}:{run.conclusion}:{sha[:12]}"
                    if run
                    else f"no_run:{sha[:12]}"
                )
            elif name == "publish" and isinstance(value, tuple):
                latest = max(value, key=lambda run: run.created_at, default=None)
                item = (
                    f"in_flight:{sum(run.is_in_flight for run in value)}"
                    if any(run.is_in_flight for run in value)
                    else (
                        "none"
                        if latest is None
                        else f"{latest.run_id}:{latest.conclusion}"
                    )
                )
            elif name == "core_pypi" and isinstance(value, tuple):
                item = f"{value[0]}@{iso_utc(value[1])}"
            else:
                item = "unparsed"
            rendered.append(f"{name}={item}")
        return (
            f"{iso_utc(self.now())} stage=watch "
            + " ".join(rendered)
            + f" action={action or 'none'}"
        )

    def _snapshot(self, values: Mapping[str, object]) -> Snapshot:
        pypi = values["pypi"]
        pr = values["release_pr"]
        full = values["full_ci"]
        gate = values["master_gate"]
        publish = values["publish"]
        core = values["core_pypi"]
        assert isinstance(pypi, tuple) and (
            pr is None or isinstance(pr, ReleasePullRequest)
        )
        assert (
            isinstance(full, tuple)
            and isinstance(gate, tuple)
            and isinstance(publish, tuple)
        )
        assert isinstance(core, tuple)
        master_sha, master_run = gate
        core_version, core_uploaded_at = core
        return Snapshot(
            pypi,
            pr,
            full,
            master_sha,
            master_run,
            publish,
            core_version,
            core_uploaded_at,
            read_ci_watch_reason(),
        )

    def evaluate(self, snapshot: Snapshot) -> tuple[str, str] | None:
        if self.options.version in snapshot.pypi_versions:
            released, details = self.install_proof()
            if released:
                return "RELEASED", details
            return "INSTALL_FAILED", details
        if snapshot.release_pr is None:
            return (
                "RELEASE_PR_GONE",
                f"no open or merged release PR carries {self.options.version}",
            )
        merged = snapshot.release_pr.merged_at
        if merged:
            failed_publish = [
                run
                for run in snapshot.publish_runs
                if run.created_at >= merged and run.conclusion in BAD_CONCLUSIONS
            ]
            if failed_publish:
                run = max(failed_publish, key=lambda item: item.created_at)
                return (
                    "PUBLISH_FAILED",
                    f"post-merge Publish run {run.run_id} failed: {run.failed_jobs}",
                )
        if self._floor_blocked(snapshot):
            return "CORE_FLOOR_BLOCKED", self._floor_blocked_detail(snapshot)
        red_runs = [run for run in snapshot.fixed_runs if run.is_red]
        deterministic = [run for run in red_runs if run.deterministic_failure]
        if deterministic or len(red_runs) >= self.options.max_red_full_ci:
            return "FULL_CI_RED", self._full_ci_red_detail(red_runs)
        return None

    def _floor_blocked(self, snapshot: Snapshot) -> bool:
        pr = snapshot.release_pr
        if pr is None or not pr.floor_failed:
            return False
        newest_core = snapshot.core_uploaded_at
        publish = [
            run for run in snapshot.publish_runs if run.created_at >= newest_core
        ]
        newest_publish = max(publish, key=lambda run: run.created_at, default=None)
        return (
            newest_publish is not None
            and pr.head_created_at > newest_publish.created_at
        )

    def _floor_blocked_detail(self, snapshot: Snapshot) -> str:
        pr = snapshot.release_pr
        assert pr is not None
        newest = max(
            (
                run
                for run in snapshot.publish_runs
                if run.created_at >= snapshot.core_uploaded_at
            ),
            key=lambda run: run.created_at,
            default=None,
        )
        return (
            f"release-core-floor-smoke still fails on PR #{pr.number} head {pr.head_sha}; "
            f"Publish after core upload: {newest.run_id if newest else 'none'}"
        )

    def _full_ci_red_detail(self, red_runs: Sequence[WorkflowRun]) -> str:
        if not red_runs:
            return "fixed-code Full CI reached the red budget with no run details"
        rows = []
        for run in red_runs:
            rows.append(
                f"run={run.run_id} url={run.url} sha={run.sha} conclusion={run.conclusion} "
                f"failed_jobs={','.join(run.failed_jobs) or 'unknown'}\nFAILED: {run.failed_excerpt or 'FAILED output unavailable'}"
            )
        return "\n\n".join(rows)

    def _deadline_detail(self, snapshot: Snapshot | None) -> str:
        reason = snapshot.ci_watch_reason if snapshot else "unknown"
        return f"deadline passed; blocking condition: ci_watch release_reason={reason}; last state: {self.last_state_line}"

    def dispatch_due(self, snapshot: Snapshot) -> list[str]:
        now = self.monotonic()
        dispatches: list[tuple[str, int, tuple[str, ...]]] = []
        full = sorted(snapshot.fixed_runs, key=lambda run: run.updated_at, reverse=True)
        fixed_red = [run for run in full if run.is_red]
        newest = full[0] if full else None
        no_full_running = not snapshot.full_in_flight
        pr_not_merged = snapshot.release_pr is None or not snapshot.release_pr.is_merged
        full_due = no_full_running and (
            newest is None
            or (newest.is_red and len(fixed_red) < self.options.max_red_full_ci)
            or (
                newest.conclusion in GOOD_CONCLUSIONS
                and self.now() - newest.updated_at > timedelta(hours=4)
                and pr_not_merged
            )
        )
        if full_due:
            dispatches.append(
                (
                    "full_ci",
                    20 * 60,
                    (
                        "workflow",
                        "run",
                        "full.yml",
                        "-R",
                        self.options.repo,
                        "--ref",
                        "master",
                    ),
                )
            )

        pr = snapshot.release_pr
        publish_runs = snapshot.publish_runs
        if pr and pr.floor_failed:
            publish_after_core = any(
                run.created_at >= snapshot.core_uploaded_at for run in publish_runs
            )
            if not publish_after_core:
                dispatches.append(
                    (
                        "floor_ratchet",
                        30 * 60,
                        (
                            "workflow",
                            "run",
                            "publish.yml",
                            "-R",
                            self.options.repo,
                            "--ref",
                            "master",
                            "-f",
                            "publish_existing=false",
                        ),
                    )
                )
        if (
            pr
            and pr.is_merged
            and not any(run.created_at >= pr.merged_at for run in publish_runs)
        ):
            dispatches.append(
                (
                    "release_publish",
                    20 * 60,
                    (
                        "workflow",
                        "run",
                        "publish.yml",
                        "-R",
                        self.options.repo,
                        "--ref",
                        "master",
                        "-f",
                        "publish_existing=false",
                    ),
                )
            )
        # A single Publish workflow dispatch satisfies both eligible reasons.
        publish_candidates = [
            item
            for item in dispatches
            if item[0] in {"floor_ratchet", "release_publish"}
        ]
        if len(publish_candidates) > 1:
            chosen = publish_candidates[0]
            dispatches = [
                item for item in dispatches if item not in publish_candidates
            ] + [chosen]

        reported: list[str] = []
        for key, cooldown, argv_tail in dispatches:
            if now - self.last_dispatch.get(key, float("-inf")) < cooldown:
                self.actions.append(f"cooldown:{key}")
                reported.append(f"cooldown:{key}")
                continue
            if self.options.dry_run or self.options.once:
                would = f"would dispatch:{key}"
                self.actions.append(would)
                reported.append(would)
                continue
            try:
                result = self.process(["gh", *argv_tail], timeout=GH_TIMEOUT)
            except WatcherSignal:
                raise
            except Exception as exc:
                failed = f"dispatch_failed:{key}:{short_exception(exc)}"
                self.actions.append(failed)
                reported.append(failed)
                continue
            if result.returncode:
                failed = f"dispatch_failed:{key}:exit_{result.returncode}"
                self.actions.append(failed)
                reported.append(failed)
                continue
            self.last_dispatch[key] = now
            self.actions.append(f"dispatched:{key}")
            reported.append(f"dispatched:{key}")
        return reported

    def install_proof(self) -> tuple[bool, str]:
        started = self.monotonic()
        retry_window = 20 * 60
        failures: list[str] = []
        while self.monotonic() - started < retry_window:
            attempt_dir = Path(tempfile.mkdtemp(prefix="sase-release-proof-"))
            try:
                success, details = self.install_attempt(attempt_dir)
                if success:
                    return True, details
                failures.append(details)
            except WatcherSignal:
                raise
            except Exception as exc:
                failures.append(short_exception(exc))
            finally:
                shutil.rmtree(attempt_dir, ignore_errors=True)
            remaining = retry_window - (self.monotonic() - started)
            if remaining > 0:
                self.sleep(min(60.0, remaining))
        excerpt = failures[-3:] or ["install proof did not run"]
        return False, "fresh-venv install proof failed for 20 minutes:\n" + "\n".join(
            excerpt
        )

    def install_attempt(self, env_dir: Path) -> tuple[bool, str]:
        uv = shutil.which("uv")
        if uv:
            python = env_dir / "bin/python"
            commands = [
                ([uv, "venv", str(env_dir)], PROCESS_TIMEOUT),
                (
                    [
                        uv,
                        "pip",
                        "install",
                        "--refresh",
                        "--python",
                        str(python),
                        f"sase=={self.options.version}",
                    ],
                    PROCESS_TIMEOUT,
                ),
                ([str(env_dir / "bin/sase"), "--version"], 30),
                (
                    [
                        str(python),
                        "-c",
                        "import importlib.metadata as m; print(m.version('sase-core-rs'))",
                    ],
                    30,
                ),
            ]
        else:
            python = env_dir / "bin/python"
            commands = [
                ([sys.executable, "-m", "venv", str(env_dir)], PROCESS_TIMEOUT),
                (
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "--upgrade",
                        "--no-cache-dir",
                        f"sase=={self.options.version}",
                    ],
                    PROCESS_TIMEOUT,
                ),
                ([str(env_dir / "bin/sase"), "--version"], 30),
                (
                    [
                        str(python),
                        "-c",
                        "import importlib.metadata as m; print(m.version('sase-core-rs'))",
                    ],
                    30,
                ),
            ]
        outputs: list[str] = []
        for index, (argv, timeout) in enumerate(commands):
            result = self.process(argv, timeout=timeout)
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode:
                return (
                    False,
                    f"command {' '.join(argv)} exited {result.returncode}: {failed_excerpt(output)}",
                )
            outputs.append((result.stdout or "").strip())
            if index == 2 and self.options.version not in outputs[-1]:
                return (
                    False,
                    f"sase --version did not report {self.options.version}: {outputs[-1]}",
                )
        core_version = outputs[-1].splitlines()[-1] if outputs[-1] else "unknown"
        return (
            True,
            f"fresh venv installed sase=={self.options.version}; sase --version={outputs[-2]}; sase-core-rs={core_version}",
        )

    def set_verdict(self, verdict: str, detail: str) -> None:
        if self.final_verdict is None:
            self.final_verdict = verdict
            self.final_detail = detail

    def _close_argv(self) -> list[str] | None:
        if not self.options.close_bead:
            return None
        assert self.verdict_path is not None
        if self.final_verdict == "RELEASED":
            return [
                "sase",
                "bead",
                "close",
                self.options.close_bead,
                "--note",
                "@" + str(self.verdict_path),
            ]
        return [
            "sase",
            "bead",
            "close",
            self.options.close_bead,
            "-R",
            "canceled",
            "-r",
            f"release not confirmed: {self.final_verdict}",
            "--note",
            "@" + str(self.verdict_path),
        ]

    def _evidence_block(self) -> str:
        verdict = self.final_verdict or "WATCHER_BROKEN"
        lines = [
            "RELEASE CONFIRMED"
            if verdict == "RELEASED"
            else f"RELEASE NOT CONFIRMED: {verdict}",
            "",
            "Evidence:",
            f"- repo: {self.options.repo}",
            f"- version: {self.options.version}",
            f"- fixed SHA: {self.options.fixed_sha}",
            f"- verdict: {verdict} (exit {EXIT_CODES[verdict]})",
            f"- detail: {self.final_detail.replace(chr(10), chr(10) + '  ')}",
            f"- actions: {', '.join(self.actions) if self.actions else 'none'}",
        ]
        for state in self.state_history:
            lines.append(f"- state: {state}")
        snapshot = self.last_snapshot
        if snapshot is not None:
            lines.append(
                "- PyPI watched version: "
                + (
                    "present"
                    if self.options.version in snapshot.pypi_versions
                    else "absent"
                )
            )
            lines.append(
                f"- sase-core-rs PyPI: {snapshot.core_version} uploaded "
                f"{iso_utc(snapshot.core_uploaded_at)}"
            )
            lines.append(f"- ci_watch release_reason: {snapshot.ci_watch_reason}")
            pr = snapshot.release_pr
            if pr is None:
                lines.append("- release PR: none")
            else:
                merged_at = iso_utc(pr.merged_at) if pr.merged_at else "not-merged"
                lines.append(
                    f"- release PR: #{pr.number} {pr.url} state={pr.state} "
                    f"merged_at={merged_at} merge_state={pr.merge_state} "
                    f"head={pr.head_sha} head_created_at={iso_utc(pr.head_created_at)}"
                )
                checks = ", ".join(
                    f"{name}={status}" for name, status in sorted(pr.checks.items())
                )
                lines.append(f"  rollup: {checks or 'none'}")
            lines.append(f"- master HEAD: {snapshot.master_sha}")
            self._append_run_evidence(
                lines,
                "Master Gate",
                (snapshot.master_gate,) if snapshot.master_gate else (),
            )
            self._append_run_evidence(lines, "Full CI", snapshot.full_runs)
            self._append_run_evidence(lines, "Publish", snapshot.publish_runs)
        lines.append(f"- last state line: {self.last_state_line}")
        lines.append(f"- close outcome: {self.close_outcome}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _append_run_evidence(
        lines: list[str], label: str, runs: Sequence[WorkflowRun]
    ) -> None:
        if not runs:
            lines.append(f"- {label} runs: none")
            return
        lines.append(f"- {label} runs:")
        for run in runs:
            jobs = (
                ",".join(
                    f"{name}={conclusion or 'in-flight'}"
                    for name, conclusion in run.jobs
                )
                or "not fetched"
            )
            lines.append(
                f"  - id={run.run_id} url={run.url} sha={run.sha} status={run.status} "
                f"conclusion={run.conclusion or 'in-flight'} "
                f"created_at={iso_utc(run.created_at)} updated_at={iso_utc(run.updated_at)} "
                f"jobs=[{jobs}]"
            )
            if run.failed_excerpt:
                lines.append(
                    "    FAILED: " + run.failed_excerpt.replace("\n", "\n    ")
                )

    def _write_verdict(self) -> None:
        assert self.verdict_path is not None
        self.verdict_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._evidence_block()
        temp = self.verdict_path.with_suffix(self.verdict_path.suffix + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(self.verdict_path)

    def _write_verdict_with_fallback(self) -> None:
        try:
            self._write_verdict()
        except OSError as exc:
            original = self.verdict_path
            self.verdict_path = (
                Path(tempfile.mkdtemp(prefix="release-watch-fallback-"))
                / "release_verdict.md"
            )
            self.final_detail += (
                f"\nCould not write verdict to {original}: {exc}; used a fallback path."
            )
            self._write_verdict()

    def finalize(self) -> int:
        if self.final_verdict is None:
            self.set_verdict("WATCHER_BROKEN", "watch ended without a verdict")
        self._finalizing = True
        self.close_outcome = "not requested"
        self._write_verdict_with_fallback()
        argv = self._close_argv()
        if argv is not None:
            if self.options.once or self.options.dry_run:
                self.close_outcome = "not run (dry-run/once)"
                self.output("close_argv=" + json.dumps(argv))
            else:
                self.close_outcome = "failed after 3 attempts"
                for attempt in range(1, 4):
                    try:
                        result = self.process(argv, timeout=GH_TIMEOUT)
                        if result.returncode == 0:
                            self.close_outcome = f"closed on attempt {attempt}"
                            break
                        self.close_outcome = f"attempt {attempt} exited {result.returncode}: {(result.stderr or '').strip()[:300]}"
                    except Exception as exc:
                        self.close_outcome = (
                            f"attempt {attempt} failed: {short_exception(exc)}"
                        )
                    if attempt < 3:
                        self.sleep(30)
                self.actions.append("bead_close:" + self.close_outcome)
        self._restore_signals()
        self._write_verdict_with_fallback()
        block = self._evidence_block()
        self.output(block.rstrip())
        self.output(f"verdict_file={self.verdict_path}")
        return EXIT_CODES[self.final_verdict or "WATCHER_BROKEN"]

    def _print_once(self, values: Mapping[str, object]) -> None:
        snapshot = self._snapshot(values)
        self.last_snapshot = snapshot
        actions = self.dispatch_due(snapshot)
        line = self._render_state(values, ",".join(actions) or "preflight")
        self.last_state_line = line
        self.state_history[-1] = line
        self.output(line)
        argv = self._close_argv()
        if argv is not None:
            self.output("close_argv=" + json.dumps(argv))


def short_exception(exc: BaseException, *, include_traceback: bool = False) -> str:
    summary = f"{type(exc).__name__}: {exc}"
    if include_traceback:
        trace = "\n".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]
        )
        summary += "\n" + trace[-1200:]
    return summary
