#!/usr/bin/env python3
"""Stdlib-only run_silent recorder: JSONL stage events and monitor diagnostics.

This helper never opens SQLite. The ToolRun parent ingests events.jsonl.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time
from typing import Any


SCHEMA_VERSION = 1
KIND_STARTED = "started"
KIND_FINISHED = "finished"
KIND_CONTINUED = "continued"
KIND_STOPPED = "stopped"
KIND_RECIPE_FINISHED = "recipe_finished"
LOCK_TIMEOUT_S = 0.25
LOCK_POLL_S = 0.005
MAX_LINE_BYTES = 65536
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_DESCRIPTION_CHARS = 1024
DEFAULT_STAGE_MAX_BYTES = 256 * 1024
DEFAULT_TOTAL_MAX_BYTES = 2 * 1024 * 1024
# Hard bound for one mid-run triage decision. Only an explicit ``continue``
# from the verb continues the recipe; the timeout, a crash, or unparseable
# output all stop. ``SASE_TOOL_TRIAGE_TIMEOUT_S`` is a test seam that only
# shortens the bound; production always waits the full default.
TRIAGE_TIMEOUT_S_DEFAULT = 10
TRIAGE_DECISION_REASONS = frozenset(
    {
        "mode_always",
        "all_known_or_flaky",
        "new_item",
        "unknown_item",
        "no_items",
        "helper_timeout",
        "helper_error",
        "mode_never",
    }
)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip().lower()).strip("-")
    return slug[:64] or "stage"


def _truncate_description(value: str) -> str:
    text = value.strip()
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[: MAX_DESCRIPTION_CHARS - 1] + "…"


def _new_id() -> str:
    return secrets.token_hex(16)


def _unix_ms() -> int:
    return int(time.time() * 1000)


def _monotonic_ns() -> int:
    return time.monotonic_ns()


def _atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _bounded_output(data: bytes, limit: int) -> tuple[bytes, list[dict[str, int]], bool]:
    if limit <= 0:
        return b"", [], True
    if len(data) <= limit:
        return data, [{"start": 0, "end": len(data)}], False
    marker = b"\n... diagnostic output truncated ...\n"
    if limit <= len(marker) + 2:
        retained = data[-limit:]
        return retained, [{"start": len(data) - len(retained), "end": len(data)}], True
    payload_budget = limit - len(marker)
    head_len = payload_budget // 2
    tail_len = payload_budget - head_len
    retained = data[:head_len] + marker + data[-tail_len:]
    ranges = [
        {"start": 0, "end": head_len},
        {"start": len(data) - tail_len, "end": len(data)},
    ]
    return retained, ranges, True


def _write_legacy_jsonl(root: str, record: dict[str, Any]) -> None:
    if not root:
        return
    root_path = pathlib.Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    with (root_path / "continuation_stage_diagnostics.jsonl").open(
        "a", encoding="utf-8"
    ) as stream:
        json.dump(record, stream, sort_keys=True)
        stream.write("\n")


def _acquire_lock(lock_stream: Any, timeout_s: float = LOCK_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_S)
        except OSError:
            return False


def append_jsonl_record(path: pathlib.Path, record: dict[str, Any]) -> bool:
    """Append one versioned JSONL record under an advisory lock. Fail open."""

    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > MAX_LINE_BYTES:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Lock the events file itself: a sibling lock file would sit outside the
        # ToolRun store's retention accounting and outlive the run's other files.
        with path.open("ab") as stream:
            if not _acquire_lock(stream):
                return False
            try:
                if os.fstat(stream.fileno()).st_size + len(encoded) > MAX_FILE_BYTES:
                    return False
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            finally:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _load_state(path: pathlib.Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: pathlib.Path, payload: dict[str, Any]) -> None:
    try:
        _atomic_write(
            path, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        )
    except OSError:
        pass


def _events_path() -> pathlib.Path | None:
    raw = (os.environ.get("SASE_TOOL_RUN_EVENTS") or "").strip()
    if not raw:
        return None
    return pathlib.Path(raw)


def _run_id() -> str:
    return (os.environ.get("SASE_TOOL_RUN_ID") or "").strip()


def start_stage(state_path: pathlib.Path, description: str) -> dict[str, Any]:
    """Write a started JSONL record and persist ids for the matching finish."""

    events_path = _events_path()
    run_id = _run_id()
    description = _truncate_description(description)
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "stage_id": _new_id(),
        "started_event_id": _new_id(),
        "finished_event_id": _new_id(),
        "description": description,
        "started_ts": _unix_ms(),
        "started_monotonic_ns": _monotonic_ns(),
        "started_at_epoch": time.time(),
    }
    _write_state(state_path, state)
    if events_path is None or not run_id:
        return state
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_STARTED,
        "run_id": run_id,
        "stage_id": state["stage_id"],
        "event_id": state["started_event_id"],
        "description": description,
        "started_ts": state["started_ts"],
        "started_monotonic_ns": state["started_monotonic_ns"],
    }
    append_jsonl_record(events_path, record)
    return state


def finish_stage(
    state_path: pathlib.Path,
    description: str,
    exit_code: int,
    output_bytes: int,
    *,
    started_at_epoch: float | None = None,
    output_source: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Write a finished JSONL record using the start state's stage id."""

    events_path = _events_path()
    run_id = _run_id()
    state = _load_state(state_path)
    description = _truncate_description(
        str(state.get("description") or description)
    )
    now_ns = _monotonic_ns()
    now_ms = _unix_ms()
    started_ns = state.get("started_monotonic_ns")
    if type(started_ns) is not int:
        started_ns = now_ns
        state["started_monotonic_ns"] = started_ns
        state["started_ts"] = state.get("started_ts") or now_ms
        state["started_at_epoch"] = state.get("started_at_epoch") or (
            started_at_epoch if started_at_epoch is not None else time.time()
        )
        state["stage_id"] = state.get("stage_id") or _new_id()
        state["finished_event_id"] = state.get("finished_event_id") or _new_id()
        state["run_id"] = state.get("run_id") or run_id
        state["description"] = description
    elapsed_ms = max(0, int((now_ns - int(started_ns)) / 1_000_000))
    state["finished_ts"] = now_ms
    state["finished_monotonic_ns"] = now_ns
    state["elapsed_ms"] = elapsed_ms
    state["exit_code"] = exit_code
    state["output_bytes"] = output_bytes
    output_path, output_truncated = _capture_failed_stage_output(
        events_path=events_path,
        state=state,
        exit_code=exit_code,
        output_source=output_source,
    )
    _write_state(state_path, state)
    if events_path is None:
        return state
    resolved_run = str(state.get("run_id") or run_id or "").strip()
    if not resolved_run:
        return state
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_FINISHED,
        "run_id": resolved_run,
        "stage_id": state["stage_id"],
        "event_id": state.get("finished_event_id") or _new_id(),
        "description": description,
        "started_ts": int(state["started_ts"]),
        "started_monotonic_ns": int(started_ns),
        "finished_ts": now_ms,
        "finished_monotonic_ns": now_ns,
        "elapsed_ms": elapsed_ms,
        "exit_code": int(exit_code),
        "output_bytes": int(output_bytes),
    }
    if output_path is not None:
        record["output_path"] = output_path
        record["output_truncated"] = output_truncated
    append_jsonl_record(events_path, record)
    return state


def _capture_failed_stage_output(
    *,
    events_path: pathlib.Path | None,
    state: dict[str, Any],
    exit_code: int,
    output_source: pathlib.Path | None,
) -> tuple[str | None, bool]:
    """Retain bounded failed-stage output beside the parent event stream."""

    if events_path is None or exit_code == 0 or output_source is None:
        return None, False
    stage_id = str(state.get("stage_id") or "").strip()
    if not stage_id:
        return None, False
    try:
        output = output_source.read_bytes()
        retained, _ranges, truncated = _bounded_output(output, DEFAULT_STAGE_MAX_BYTES)
        target = events_path.parent / "stage_output" / f"{stage_id}.log"
        _atomic_write(target, retained)
        return target.relative_to(events_path.parent).as_posix(), truncated
    except OSError:
        return None, False


def _continuation_summary(events_path: pathlib.Path, run_id: str) -> tuple[int, int | None]:
    """Return the continued-stage count and first continued exit code.

    JSONL is append-only and the stage wrapper runs serially in a recipe, so
    file order is the authoritative order for the first failure. Malformed
    records are ignored: they must never make a recipe accidentally succeed.
    """

    count = 0
    first_code: int | None = None
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return count, first_code
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("kind") != KIND_CONTINUED or record.get("run_id") != run_id:
            continue
        code = record.get("exit_code")
        if type(code) is not int or code == 0:
            continue
        count += 1
        if first_code is None:
            first_code = code
    return count, first_code


def _append_continuation(
    kind: str,
    *,
    state_path: pathlib.Path | None = None,
    mode: str | None = None,
    exit_code: int | None = None,
    reason: str | None = None,
    elapsed_ms: int | None = None,
    description: str | None = None,
) -> tuple[bool, int | None]:
    """Append one continuation fact, returning its prior first failure code."""

    events_path = _events_path()
    run_id = _run_id()
    if events_path is None or not run_id:
        return False, None
    _, first_code = _continuation_summary(events_path, run_id)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "run_id": run_id,
        "event_id": _new_id(),
        "decided_ts": _unix_ms(),
    }
    if state_path is not None:
        state = _load_state(state_path)
        stage_id = str(state.get("stage_id") or "").strip()
        if not stage_id:
            return False, first_code
        record["stage_id"] = stage_id
    if mode is not None:
        record["mode"] = mode
    if exit_code is not None:
        record["exit_code"] = int(exit_code)
    if reason is not None:
        record["reason"] = reason
    if elapsed_ms is not None:
        record["elapsed_ms"] = max(0, int(elapsed_ms))
    if description is not None:
        record["description"] = str(description)
    if kind == KIND_RECIPE_FINISHED:
        record["first_continued_exit_code"] = first_code
    return append_jsonl_record(events_path, record), first_code


def decide_stage(
    state_path: pathlib.Path,
    description: str,
    exit_code: int,
    mode: str,
) -> int:
    """Persist a continuation decision and return the recipe-visible status.

    ``0`` is reserved for a successfully recorded continuation. A failed
    decision remains fail-fast, using the first earlier continued code to
    retain ordinary fail-fast exit-code parity.
    """

    started = _monotonic_ns()
    if mode == "always":
        recorded, _ = _append_continuation(
            KIND_CONTINUED,
            state_path=state_path,
            mode=mode,
            exit_code=exit_code,
            reason="mode_always",
            elapsed_ms=int((_monotonic_ns() - started) / 1_000_000),
            description=description,
        )
        return 0 if recorded else exit_code

    if mode == "known":
        decision, reason = _spawn_triage_decision(state_path, description)
        kind = KIND_CONTINUED if decision == "continue" else KIND_STOPPED
        recorded, first_code = _append_continuation(
            kind,
            state_path=state_path,
            mode=mode,
            exit_code=exit_code,
            reason=reason,
            elapsed_ms=int((_monotonic_ns() - started) / 1_000_000),
            description=description,
        )
        if kind == KIND_CONTINUED:
            return 0 if recorded else exit_code
        if not recorded:
            return exit_code
        return first_code if first_code is not None else exit_code

    # An unknown value follows the same safe stop behavior as ``never``.
    reason = "mode_never" if mode == "never" else "helper_error"
    recorded, first_code = _append_continuation(
        KIND_STOPPED,
        state_path=state_path,
        mode=mode,
        exit_code=exit_code,
        reason=reason,
        elapsed_ms=int((_monotonic_ns() - started) / 1_000_000),
        description=description,
    )
    if not recorded:
        return exit_code
    return first_code if first_code is not None else exit_code


def _triage_timeout_s() -> int:
    """Return the hard bound for one mid-run triage decision in seconds."""

    raw = (os.environ.get("SASE_TOOL_TRIAGE_TIMEOUT_S") or "").strip()
    try:
        value = int(raw) if raw else TRIAGE_TIMEOUT_S_DEFAULT
    except ValueError:
        return TRIAGE_TIMEOUT_S_DEFAULT
    if value < 1:
        return 1
    return min(value, TRIAGE_TIMEOUT_S_DEFAULT)


def _parse_triage_answer(raw: bytes) -> tuple[str, str]:
    """Reduce the verb's stdout to a ``(decision, reason)`` pair."""

    try:
        text = raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - undecodable output stops.
        return "stop", "helper_error"
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            answer = json.loads(stripped)
        except json.JSONDecodeError:
            return "stop", "helper_error"
        if not isinstance(answer, dict):
            return "stop", "helper_error"
        reason = answer.get("reason")
        if reason not in TRIAGE_DECISION_REASONS:
            reason = "helper_error"
        if answer.get("decision") == "continue" and reason == "all_known_or_flaky":
            return "continue", reason
        if answer.get("decision") == "stop":
            return "stop", reason
        return "stop", "helper_error"
    return "stop", "helper_error"


def _spawn_triage_decision(
    state_path: pathlib.Path, description: str
) -> tuple[str, str]:
    """Ask the hidden triage verb whether a failed stage may continue.

    Returns a ``(decision, reason)`` pair. Only an explicit ``continue``
    continues; the timeout, a crash, unparseable output, or a missing
    handshake all stop.
    """

    events_path = _events_path()
    run_id = _run_id()
    python = (os.environ.get("SASE_TOOL_PYTHON") or "").strip()
    state = _load_state(state_path)
    stage_id = str(state.get("stage_id") or "").strip()
    if events_path is None or not run_id or not python or not stage_id:
        return "stop", "helper_error"
    output = events_path.parent / "stage_output" / f"{stage_id}.log"
    argv = [
        python,
        "-m",
        "sase",
        "tool",
        "_triage-stage",
        run_id,
        "--stage-id",
        stage_id,
        "--description",
        description,
        "--output",
        str(output),
    ]
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return "stop", "helper_error"
    try:
        raw, _ = proc.communicate(timeout=_triage_timeout_s())
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        proc.wait()
        return "stop", "helper_timeout"
    except Exception:  # noqa: BLE001 - a failed wait stops.
        return "stop", "helper_error"
    decision, reason = _parse_triage_answer(raw or b"")
    if decision == "continue" and proc.returncode == 0:
        return "continue", reason
    return "stop", reason


def finish_recipe() -> int:
    """Record recipe completion and restore the first continued failure code."""

    recorded, first_code = _append_continuation(KIND_RECIPE_FINISHED)
    if not recorded or first_code is None:
        return 0
    events_path = _events_path()
    run_id = _run_id()
    count, _ = (
        _continuation_summary(events_path, run_id)
        if events_path is not None and run_id
        else (0, None)
    )
    print(
        f"✗ {count} stage(s) failed; continued past them (first exit {first_code})"
    )
    return first_code


def _write_monitor_stage(
    root: str,
    record: dict[str, Any],
    output: bytes,
    description: str,
    *,
    started_at_epoch: float,
    elapsed_seconds: float,
) -> None:
    if not root:
        return
    root_path = pathlib.Path(root)
    lock_path = root_path / ".diagnostics.lock"
    root_path.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        stage_id = (
            f"{_slug(description)}-{os.getpid()}-{time.time_ns()}-"
            f"{hashlib.sha256(description.encode()).hexdigest()[:8]}"
        )
        stage = {
            "stage_id": stage_id,
            "name": description,
            "status": record["status"],
            "exit_code": record["exit_code"],
            "diagnostic_refs": [],
            "diagnostic_locators": [],
            "counts": {
                "output_bytes": record["output_bytes"],
                "output_lines": record["output_lines"],
            },
            "retained_ranges": [],
            "capture_errors": [],
            "recorded_at_epoch": record["recorded_at_epoch"],
            "started_at_epoch": started_at_epoch,
            "elapsed_seconds": elapsed_seconds,
        }
        if os.environ.get("SASE_RUN_SILENT_FORCE_CAPTURE_ERROR"):
            stage["capture_errors"].append("forced diagnostic capture error")
        elif record["exit_code"] != 0:
            evidence_dir = root_path / "stage_output"
            stage_max = _int_env(
                "SASE_MONITOR_STAGE_DIAGNOSTIC_MAX_BYTES", DEFAULT_STAGE_MAX_BYTES
            )
            total_max = _int_env(
                "SASE_MONITOR_DIAGNOSTIC_TOTAL_MAX_BYTES", DEFAULT_TOTAL_MAX_BYTES
            )
            existing = sum(
                path.stat().st_size
                for path in evidence_dir.glob("*.log")
                if path.is_file()
            )
            allowed = min(stage_max, max(0, total_max - existing))
            if allowed <= 0:
                stage["capture_errors"].append("diagnostic quota exceeded")
            else:
                retained, ranges, truncated = _bounded_output(output, allowed)
                evidence_path = evidence_dir / f"{stage_id}.log"
                try:
                    _atomic_write(evidence_path, retained)
                except OSError as exc:
                    stage["capture_errors"].append(f"could not write diagnostic: {exc}")
                else:
                    locator = evidence_path.relative_to(root_path.parent).as_posix()
                    stage["diagnostic_refs"].append(f"file:monitor-stage:{stage_id}")
                    stage["diagnostic_locators"].append(locator)
                    stage["retained_ranges"] = ranges
                    stage["counts"]["retained_bytes"] = len(retained)
                    if truncated:
                        stage["capture_errors"].append(
                            "diagnostic output truncated to "
                            f"{len(retained)} of {len(output)} bytes"
                        )
        _atomic_write(
            root_path / "stages" / f"{stage_id}.json",
            (json.dumps(stage, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )


def record_diagnostics(
    description: str,
    exit_code: int,
    output_path: pathlib.Path,
    *,
    started_at_epoch: float,
) -> None:
    monitor_dir = os.environ.get("SASE_MONITOR_DIAGNOSTICS_DIR") or ""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR") or ""
    if not monitor_dir and not artifacts_dir:
        return
    try:
        output = output_path.read_bytes()
    except OSError:
        output = b""
    elapsed_seconds = max(0.0, time.time() - started_at_epoch)
    record = {
        "schema_version": SCHEMA_VERSION,
        "producer": "tools/run_silent",
        "description": description,
        "exit_code": int(exit_code),
        "status": "passed" if int(exit_code) == 0 else "failed",
        "output_bytes": len(output),
        "output_lines": output.count(b"\n"),
        "recorded_at_epoch": time.time(),
        "started_at_epoch": started_at_epoch,
        "elapsed_seconds": elapsed_seconds,
    }
    try:
        _write_legacy_jsonl(artifacts_dir, record)
        _write_monitor_stage(
            monitor_dir,
            record,
            output,
            description,
            started_at_epoch=started_at_epoch,
            elapsed_seconds=elapsed_seconds,
        )
    except Exception:
        return


def _parse_started_at(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--state", required=True)
    start.add_argument("--description", required=True)

    finish = sub.add_parser("finish")
    finish.add_argument("--state", required=True)
    finish.add_argument("--description", required=True)
    finish.add_argument("--exit-code", required=True, type=int)
    finish.add_argument("--output", required=True)
    finish.add_argument("--started-at", default="")

    decide = sub.add_parser("decide")
    decide.add_argument("--state", required=True)
    decide.add_argument("--description", required=True)
    decide.add_argument("--exit-code", required=True, type=int)
    decide.add_argument("--mode", required=True)

    sub.add_parser("recipe-finish")

    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            start_stage(pathlib.Path(args.state), args.description)
            return 0
        if args.command == "decide":
            return decide_stage(
                pathlib.Path(args.state),
                args.description,
                args.exit_code,
                args.mode,
            )
        if args.command == "recipe-finish":
            return finish_recipe()
        output_path = pathlib.Path(args.output)
        try:
            output_bytes = output_path.stat().st_size
        except OSError:
            output_bytes = 0
        started_at = _parse_started_at(args.started_at)
        state = finish_stage(
            pathlib.Path(args.state),
            args.description,
            args.exit_code,
            output_bytes,
            started_at_epoch=started_at,
            output_source=output_path,
        )
        started_epoch = started_at
        if started_epoch is None:
            raw = state.get("started_at_epoch")
            started_epoch = float(raw) if isinstance(raw, (int, float)) else time.time()
        record_diagnostics(
            args.description,
            args.exit_code,
            output_path,
            started_at_epoch=float(started_epoch),
        )
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
