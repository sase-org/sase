"""Configurable commands that run before and after commit dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO, Literal
import uuid

from sase.config.core import load_merged_config
from sase.output import print_status
from sase.workflows.commit.hook_utils import get_repo_root

CommitHookPhase = Literal["before", "after"]

HOOK_LOG_DIRNAME = "commit_hooks"
_LOG_CAP_BYTES = 1_048_576
_TAIL_CAP_BYTES = 16_384
_READ_CHUNK_BYTES = 65_536
_READER_JOIN_SECONDS = 1.0


@dataclass(frozen=True)
class _HookLogPaths:
    metadata: Path
    stdout: Path
    stderr: Path
    stdout_tail: Path
    stderr_tail: Path


@dataclass(frozen=True)
class _HookRunResult:
    returncode: int
    duration_seconds: float
    metadata_path: Path
    stdout_tail: str
    stderr_tail: str
    stdout_truncated: bool
    stderr_truncated: bool


def _run_commit_hook(phase: CommitHookPhase, cwd: str) -> bool:
    """Run the configured hook for *phase* in the repository root."""
    config = load_merged_config()
    hooks = config.get("commit_hooks", {})
    cmd = hooks.get(phase, "") if isinstance(hooks, dict) else ""
    if not cmd:
        return True
    repo_root = get_repo_root(cwd) or cwd
    print_status(f"Running {phase} commit hook: {cmd}", "progress")
    result = _run_hook_command(cmd, phase=phase, repo_root=repo_root)
    if result.returncode != 0:
        print_status(
            f"{phase.capitalize()} commit hook failed "
            f"(exit {result.returncode}): {cmd}",
            "error",
        )
        print_status(
            f"{phase.capitalize()} commit hook evidence: {result.metadata_path}",
            "warning",
        )
        tail = _commit_hook_output_tail(result.stdout_tail, result.stderr_tail)
        if tail:
            print(f"---- {phase} commit hook output tail ----", file=sys.stderr)
            print(tail, file=sys.stderr)
            print(f"---- end {phase} commit hook output ----", file=sys.stderr)
        return False
    return True


def run_before_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.before`` in the repository root."""
    return _run_commit_hook("before", cwd)


def run_after_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.after`` in the repository root."""
    return _run_commit_hook("after", cwd)


def _commit_hook_output_tail(stdout: str, stderr: str, *, max_lines: int = 50) -> str:
    """Return the last useful lines from captured commit-hook output."""
    lines: list[str] = []
    for label, text in (("stdout", stdout), ("stderr", stderr)):
        if not text:
            continue
        section = text.rstrip().splitlines()
        if not section:
            continue
        lines.append(f"[{label}]")
        lines.extend(section)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _run_hook_command(
    cmd: str,
    *,
    phase: CommitHookPhase,
    repo_root: str,
) -> _HookRunResult:
    root = _hook_log_root()
    root.mkdir(parents=True, exist_ok=True)
    repo_digest = _repo_digest(repo_root)
    stem = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')}"
        f".{phase}.{repo_digest}.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    )
    paths = _HookLogPaths(
        metadata=root / f"{stem}.json",
        stdout=root / f"{stem}.stdout.log",
        stderr=root / f"{stem}.stderr.log",
        stdout_tail=root / f"{stem}.stdout.tail",
        stderr_tail=root / f"{stem}.stderr.tail",
    )
    started = time.monotonic()
    metadata: dict[str, object] = {
        "schema_version": 1,
        "status": "starting",
        "command": cmd,
        "phase": phase,
        "repo_root": _normalize_path(repo_root),
        "repo_digest": repo_digest,
        "start_time": datetime.now(UTC).isoformat(),
        "start_time_epoch": time.time(),
        "invocation": {
            "agent_name": os.environ.get("SASE_AGENT_NAME", ""),
            "agent_timestamp": os.environ.get("SASE_AGENT_TIMESTAMP", ""),
            "artifacts_dir": os.environ.get("SASE_ARTIFACTS_DIR", ""),
        },
        "paths": {
            "metadata": str(paths.metadata),
            "stdout": str(paths.stdout),
            "stderr": str(paths.stderr),
            "stdout_tail": str(paths.stdout_tail),
            "stderr_tail": str(paths.stderr_tail),
        },
    }
    _write_json_atomic(paths.metadata, metadata)
    for path in (paths.stdout, paths.stderr, paths.stdout_tail, paths.stderr_tail):
        path.touch(exist_ok=False)
    print_status(f"{phase.capitalize()} commit hook evidence: {paths.metadata}", "info")

    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as exc:
        duration = time.monotonic() - started
        metadata.update(
            {
                "status": "failed_to_start",
                "returncode": 127,
                "duration_seconds": duration,
                "error": str(exc),
            }
        )
        _write_json_atomic(paths.metadata, metadata)
        return _HookRunResult(
            returncode=127,
            duration_seconds=duration,
            metadata_path=paths.metadata,
            stdout_tail="",
            stderr_tail=str(exc),
            stdout_truncated=False,
            stderr_truncated=False,
        )

    metadata.update({"status": "running", "pid": process.pid})
    _write_json_atomic(paths.metadata, metadata)

    lock = threading.Lock()
    written = {"stdout": 0, "stderr": 0}
    truncated = {"stdout": False, "stderr": False}
    tails = {"stdout": bytearray(), "stderr": bytearray()}

    threads = [
        threading.Thread(
            target=_drain_stream,
            args=(
                process.stdout,
                "stdout",
                paths.stdout,
                paths.stdout_tail,
                lock,
                written,
                truncated,
                tails,
            ),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_stream,
            args=(
                process.stderr,
                "stderr",
                paths.stderr,
                paths.stderr_tail,
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
    returncode = process.wait()
    for thread in threads:
        thread.join(timeout=_READER_JOIN_SECONDS)

    duration = time.monotonic() - started
    with lock:
        stdout_tail = _decode_tail(tails["stdout"])
        stderr_tail = _decode_tail(tails["stderr"])
        stdout_truncated = truncated["stdout"]
        stderr_truncated = truncated["stderr"]
    metadata.update(
        {
            "status": "success" if returncode == 0 else "failed",
            "returncode": returncode,
            "duration_seconds": duration,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "end_time": datetime.now(UTC).isoformat(),
        }
    )
    _write_json_atomic(paths.metadata, metadata)
    return _HookRunResult(
        returncode=returncode,
        duration_seconds=duration,
        metadata_path=paths.metadata,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _drain_stream(
    stream: BinaryIO | None,
    name: Literal["stdout", "stderr"],
    log_path: Path,
    tail_path: Path,
    lock: threading.Lock,
    written: dict[str, int],
    truncated: dict[str, bool],
    tails: dict[str, bytearray],
) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            with lock:
                _append_bounded_log(log_path, name, chunk, written, truncated)
                tails[name].extend(chunk)
                if len(tails[name]) > _TAIL_CAP_BYTES:
                    del tails[name][: len(tails[name]) - _TAIL_CAP_BYTES]
                _write_bytes_atomic(tail_path, bytes(tails[name]))
    except OSError:
        return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _append_bounded_log(
    path: Path,
    name: Literal["stdout", "stderr"],
    chunk: bytes,
    written: dict[str, int],
    truncated: dict[str, bool],
) -> None:
    if truncated[name]:
        return
    room = _LOG_CAP_BYTES - written[name]
    with path.open("ab") as handle:
        if len(chunk) <= room:
            handle.write(chunk)
            written[name] += len(chunk)
            return
        if room > 0:
            handle.write(chunk[:room])
            written[name] += room
        marker = (
            f"\n[commit hook {name} log truncated after {_LOG_CAP_BYTES} bytes; "
            "see the .tail file for recent output]\n"
        ).encode()
        handle.write(marker)
        truncated[name] = True


def _hook_log_root() -> Path:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "").strip()
    if artifacts_dir:
        return Path(artifacts_dir) / HOOK_LOG_DIRNAME
    owner = str(getattr(os, "getuid", lambda: "user")())
    return Path(tempfile.gettempdir()) / "sase-commit-hooks" / owner


def load_latest_commit_hook_metadata(
    artifacts: str | os.PathLike[str] | None,
    repo_path: str,
) -> dict[str, object] | None:
    """Return the newest hook metadata for *repo_path* under *artifacts*."""
    if artifacts is None:
        return None
    root = Path(artifacts) / HOOK_LOG_DIRNAME
    try:
        candidates = list(root.glob("*.json"))
    except OSError:
        return None
    repo_norm = _normalize_path(repo_path)
    newest: tuple[float, dict[str, object]] | None = None
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if _normalize_path(str(data.get("repo_root") or "")) != repo_norm:
            continue
        data["metadata_path"] = str(path)
        start = data.get("start_time_epoch")
        if not isinstance(start, (int, float)):
            try:
                start = path.stat().st_mtime
            except OSError:
                start = 0.0
        if newest is None or float(start) > newest[0]:
            newest = (float(start), data)
    return newest[1] if newest is not None else None


def hook_output_tail_from_metadata(metadata: dict[str, object]) -> str:
    paths = metadata.get("paths")
    if not isinstance(paths, dict):
        return ""
    stdout_tail = _read_text_path(paths.get("stdout_tail"))
    stderr_tail = _read_text_path(paths.get("stderr_tail"))
    return _commit_hook_output_tail(stdout_tail, stderr_tail)


def _read_text_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return Path(value).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _decode_tail(value: bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


def _repo_digest(repo_root: str) -> str:
    return hashlib.sha256(_normalize_path(repo_root).encode("utf-8")).hexdigest()[:12]


def _normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))
