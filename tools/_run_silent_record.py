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
import sys
import time
from typing import Any


SCHEMA_VERSION = 1
KIND_STARTED = "started"
KIND_FINISHED = "finished"
LOCK_TIMEOUT_S = 0.25
LOCK_POLL_S = 0.005
MAX_LINE_BYTES = 65536
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_DESCRIPTION_CHARS = 1024
DEFAULT_STAGE_MAX_BYTES = 256 * 1024
DEFAULT_TOTAL_MAX_BYTES = 2 * 1024 * 1024


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
    append_jsonl_record(events_path, record)
    return state


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

    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            start_stage(pathlib.Path(args.state), args.description)
            return 0
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
