"""Per-lumberjack state directories, PIDs, status, metrics, and logs.

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so home-directory redirection applies to every reader.
"""

import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import sase.axe.state as _state

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS = 5 * 60
_TRUNCATION_MARKER = b"[sase] lumberjack log truncated to most recent output\n"


@dataclass
class LumberjackStatus:
    """Status of a single lumberjack process."""

    name: str
    pid: int
    started_at: str
    status: Literal["running", "stopped", "error"]
    interval: int
    chops: list[str] = field(default_factory=list)
    last_cycle: str | None = None
    cycles_run: int = 0
    errors_encountered: int = 0
    uptime_seconds: int = 0


@dataclass
class LumberjackMetrics:
    """Cumulative metrics for a single lumberjack process."""

    cycles_run: int = 0
    chops_executed: int = 0
    total_updates: int = 0
    errors_encountered: int = 0


def lumberjack_state_dir(name: str) -> Path:
    """Return the state directory for a given lumberjack.

    Args:
        name: Lumberjack name (e.g. "hooks", "checks").

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/``.
    """
    return _state.jack_state_dir() / name


def ensure_lumberjack_dirs(name: str) -> Path:
    """Create the per-lumberjack state directory tree.

    Creates::

        ~/.sase/axe/lumberjacks/{name}/
        ~/.sase/axe/lumberjacks/{name}/logs/

    Args:
        name: Lumberjack name.

    Returns:
        Path to the lumberjack state directory.
    """
    lumberjack_dir = lumberjack_state_dir(name)
    (lumberjack_dir / "logs").mkdir(parents=True, exist_ok=True)
    return lumberjack_dir


def write_lumberjack_pid(name: str) -> None:
    """Write PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    (lumberjack_dir / "pid").write_text(str(os.getpid()))


def read_lumberjack_pid(name: str) -> int | None:
    """Read PID for a lumberjack process.

    Args:
        name: Lumberjack name.

    Returns:
        PID as integer, or None if not found.
    """
    pid_file = lumberjack_state_dir(name) / "pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_lumberjack_pid(name: str) -> None:
    """Remove PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    pid_file = lumberjack_state_dir(name) / "pid"
    try:
        pid_file.unlink()
    except OSError:
        pass


def write_lumberjack_status(status: LumberjackStatus) -> None:
    """Write lumberjack status to disk.

    Args:
        status: Current lumberjack status.
    """
    lumberjack_dir = ensure_lumberjack_dirs(status.name)
    _state.atomic_write_json(lumberjack_dir / "status.json", asdict(status))


def read_lumberjack_status(name: str) -> LumberjackStatus | None:
    """Read lumberjack status from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackStatus, or None if not available.
    """
    status_file = lumberjack_state_dir(name) / "status.json"
    data = _state.read_json(status_file)
    if data is None:
        return None
    try:
        return LumberjackStatus(**data)
    except TypeError:
        return None


def write_lumberjack_metrics(name: str, metrics: LumberjackMetrics) -> None:
    """Write lumberjack metrics to disk.

    Args:
        name: Lumberjack name.
        metrics: Current metrics.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    _state.atomic_write_json(lumberjack_dir / "metrics.json", asdict(metrics))


def read_lumberjack_metrics(name: str) -> LumberjackMetrics | None:
    """Read lumberjack metrics from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackMetrics, or None if not available.
    """
    metrics_file = lumberjack_state_dir(name) / "metrics.json"
    data = _state.read_json(metrics_file)
    if data is None:
        return None
    try:
        return LumberjackMetrics(**data)
    except TypeError:
        return None


def write_chop_timestamps(name: str, timestamps: dict[str, str]) -> None:
    """Write chop last-run timestamps to disk.

    Args:
        name: Lumberjack name.
        timestamps: Mapping of chop name to ISO timestamp string.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    _state.atomic_write_json(lumberjack_dir / "chop_timestamps.json", timestamps)


def read_chop_timestamps(name: str) -> dict[str, str]:
    """Read chop last-run timestamps from disk.

    Args:
        name: Lumberjack name.

    Returns:
        Mapping of chop name to ISO timestamp string, or empty dict.
    """
    timestamps_file = lumberjack_state_dir(name) / "chop_timestamps.json"
    data = _state.read_json(timestamps_file)
    if data is None or not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def lumberjack_log_path(name: str) -> Path:
    """Return the output log path for a lumberjack.

    Args:
        name: Lumberjack name.

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/logs/output.log``.
    """
    return lumberjack_state_dir(name) / "logs" / "output.log"


def append_bounded_log(
    path: Path,
    text: str | bytes,
    *,
    max_bytes: int = DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
    temp_max_age_seconds: int = DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
) -> None:
    """Append to a log file while keeping it below ``max_bytes``.

    The common path is a normal append.  When the write would cross the cap,
    only the bounded tail of the existing file is read and an atomic replace
    installs the truncated file.
    """
    data = text.encode("utf-8", errors="replace") if isinstance(text, str) else text
    if not data:
        return

    cap = max(1, int(max_bytes))
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        current_size = path.stat().st_size
    except FileNotFoundError:
        current_size = 0
    except OSError:
        return

    if current_size + len(data) <= cap:
        try:
            with open(path, "ab") as f:
                f.write(data)
        except OSError:
            pass
        return

    retained_cap = max(1, cap // 2)
    tail_budget = max(0, retained_cap - len(_TRUNCATION_MARKER) - len(data))
    tail = _read_tail_bytes(path, tail_budget)
    payload = (_TRUNCATION_MARKER + tail + data)[-retained_cap:]
    _atomic_replace_bytes(
        path,
        payload,
        temp_max_age_seconds=temp_max_age_seconds,
    )


def append_lumberjack_log(
    name: str,
    text: str | bytes,
    *,
    max_bytes: int = DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
    temp_max_age_seconds: int = DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
) -> None:
    """Append to a lumberjack's aggregate output log with a byte cap."""
    append_bounded_log(
        lumberjack_log_path(name),
        text,
        max_bytes=max_bytes,
        temp_max_age_seconds=temp_max_age_seconds,
    )


def _read_tail_bytes(path: Path, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        return b""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read(max_bytes)
    except OSError:
        return b""


def reap_stale_log_rotation_temps(
    root: Path,
    *,
    max_age_seconds: int = DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
) -> int:
    """Best-effort remove stale bounded-log rotation temps below ``root``."""
    cutoff = time.time() - max(0, max_age_seconds)
    reaped = 0

    def ignore_walk_error(_error: OSError) -> None:
        return

    for directory, _subdirs, filenames in os.walk(root, onerror=ignore_walk_error):
        for filename in filenames:
            if not _is_log_rotation_temp_name(filename):
                continue
            candidate = Path(directory) / filename
            try:
                if candidate.stat().st_mtime > cutoff:
                    continue
                candidate.unlink()
                reaped += 1
            except OSError:
                pass
    return reaped


def _is_log_rotation_temp_name(
    filename: str, *, target_name: str | None = None
) -> bool:
    if target_name is not None:
        return filename.startswith(f".{target_name}.") and filename.endswith(".tmp")
    return (
        filename.startswith(".") and ".log." in filename and filename.endswith(".tmp")
    )


def _reap_stale_rotation_temps_for_path(
    path: Path,
    *,
    max_age_seconds: int,
) -> None:
    cutoff = time.time() - max(0, max_age_seconds)
    try:
        siblings = path.parent.iterdir()
        for candidate in siblings:
            if not _is_log_rotation_temp_name(candidate.name, target_name=path.name):
                continue
            try:
                if candidate.stat().st_mtime <= cutoff:
                    candidate.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _atomic_replace_bytes(
    path: Path,
    data: bytes,
    *,
    temp_max_age_seconds: int = DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
) -> None:
    temp_name: str | None = None
    _reap_stale_rotation_temps_for_path(
        path,
        max_age_seconds=temp_max_age_seconds,
    )
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_name = f.name
            f.write(data)
        os.replace(temp_name, path)
    except OSError:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except OSError:
                pass


def read_lumberjack_log_tail(name: str, lines: int = 1000) -> str:
    """Read the last N lines of a lumberjack's output log.

    Args:
        name: Lumberjack name.
        lines: Number of lines to read from the end (default: 1000).

    Returns:
        String with the last N lines (ANSI codes preserved).
    """
    log_file = lumberjack_log_path(name)
    if not log_file.exists():
        return ""
    return _state.read_tail_seek(log_file, lines)


def clear_lumberjack_output_log(name: str) -> None:
    """Clear a lumberjack's output log file.

    Args:
        name: Lumberjack name.
    """
    log_file = lumberjack_log_path(name)
    if log_file.exists():
        try:
            log_file.write_text("")
        except OSError:
            pass


def list_lumberjack_names() -> list[str]:
    """List all lumberjack names that have state directories.

    Returns:
        Sorted list of lumberjack names.
    """
    jack_root = _state.jack_state_dir()
    if not jack_root.exists():
        return []
    return sorted(d.name for d in jack_root.iterdir() if d.is_dir())


def ensure_shared_dir() -> Path:
    """Create and return the shared state directory.

    Returns:
        Path to ``~/.sase/axe/shared/``.
    """
    shared_dir = _state.shared_state_dir()
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir
