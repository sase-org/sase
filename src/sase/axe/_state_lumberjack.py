"""Per-lumberjack state directories, PIDs, status, metrics, and logs.

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so home-directory redirection applies to every reader.
"""

import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

import sase.axe.state as _state
from sase.core.state_write_guard import best_effort_test_state_write_allowed

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS = 5 * 60
_TRUNCATION_MARKER = b"[sase] lumberjack log truncated to most recent output\n"

CHOP_SKIP_TRIGGER = "trigger"
CHOP_SKIP_RUN_EVERY = "run_every"
CHOP_SKIP_INHIBITED = "inhibited"
CHOP_SKIP_REASONS = (
    CHOP_SKIP_TRIGGER,
    CHOP_SKIP_RUN_EVERY,
    CHOP_SKIP_INHIBITED,
)


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
    last_tick_spawns: int = 0
    last_tick_skipped: int = 0
    last_tick_no_ops: int = 0
    spawn_rate_per_minute: float = 0.0
    no_op_ratio: float = 0.0


@dataclass
class LumberjackMetrics:
    """Cumulative metrics for a single lumberjack process."""

    cycles_run: int = 0
    chops_executed: int = 0
    total_updates: int = 0
    errors_encountered: int = 0
    chops_spawned: int = 0
    chops_no_op: int = 0
    chops_skipped: dict[str, int] = field(default_factory=dict)
    last_tick_spawns: int = 0
    last_tick_skipped: int = 0
    last_tick_no_ops: int = 0
    last_tick_at: str | None = None
    spawn_rate_per_minute: float = 0.0
    no_op_ratio: float = 0.0

    def record_skips(self, reason: str, count: int = 1) -> None:
        """Increment one skip-reason bucket. Unknown reasons are still counted."""
        if count <= 0:
            return
        self.chops_skipped[reason] = self.chops_skipped.get(reason, 0) + count

    def skipped_total(self) -> int:
        """Return the sum of every skip-reason bucket."""
        return sum(self.chops_skipped.values())


def format_no_op_ratio(metrics: LumberjackMetrics | None) -> str:
    """Render no-op ratio as a percent, or ``n/a`` when nothing has spawned."""
    if metrics is None or metrics.chops_spawned <= 0:
        return "n/a"
    return f"{metrics.no_op_ratio:.0%}"


def format_lumberjack_chop_load(metrics: LumberjackMetrics | None) -> str:
    """Compact spawn-rate / no-op / last-tick summary for status UIs."""
    if metrics is None:
        return "-"
    return (
        f"{metrics.spawn_rate_per_minute:.1f}/min"
        f" · no-op={format_no_op_ratio(metrics)}"
        f"\ntick {metrics.last_tick_spawns}/{metrics.last_tick_skipped}"
        f"\nt={metrics.chops_skipped.get(CHOP_SKIP_TRIGGER, 0)}"
        f" re={metrics.chops_skipped.get(CHOP_SKIP_RUN_EVERY, 0)}"
        f" inh={metrics.chops_skipped.get(CHOP_SKIP_INHIBITED, 0)}"
    )


def _dataclass_from_mapping(cls: type[Any], data: dict[str, Any]) -> Any | None:
    """Build ``cls`` from JSON, ignoring unknown keys so older readers stay safe."""
    try:
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in allowed})
    except TypeError:
        return None


def _coerce_lumberjack_metrics(metrics: LumberjackMetrics) -> LumberjackMetrics:
    raw_skipped = metrics.chops_skipped
    cleaned: dict[str, int] = {}
    if isinstance(raw_skipped, dict):
        for key, value in raw_skipped.items():
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                cleaned[str(key)] = value
    metrics.chops_skipped = cleaned
    for attr in ("spawn_rate_per_minute", "no_op_ratio"):
        raw = getattr(metrics, attr)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            setattr(metrics, attr, 0.0)
        else:
            setattr(metrics, attr, float(raw))
    for attr in (
        "chops_spawned",
        "chops_no_op",
        "last_tick_spawns",
        "last_tick_skipped",
        "last_tick_no_ops",
    ):
        raw = getattr(metrics, attr)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            setattr(metrics, attr, 0)
    if metrics.last_tick_at is not None and not isinstance(metrics.last_tick_at, str):
        metrics.last_tick_at = None
    return metrics


def _coerce_lumberjack_status(status: LumberjackStatus) -> LumberjackStatus:
    for attr in ("last_tick_spawns", "last_tick_skipped", "last_tick_no_ops"):
        raw = getattr(status, attr)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            setattr(status, attr, 0)
    for attr in ("spawn_rate_per_minute", "no_op_ratio"):
        raw = getattr(status, attr)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            setattr(status, attr, 0.0)
        else:
            setattr(status, attr, float(raw))
    return status


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
    if not best_effort_test_state_write_allowed(
        lumberjack_dir, category="axe-lumberjack-state"
    ):
        return lumberjack_dir
    (lumberjack_dir / "logs").mkdir(parents=True, exist_ok=True)
    return lumberjack_dir


def write_lumberjack_pid(name: str) -> None:
    """Write PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    pid_file = lumberjack_state_dir(name) / "pid"
    if not best_effort_test_state_write_allowed(
        pid_file, category="axe-lumberjack-pid"
    ):
        return
    ensure_lumberjack_dirs(name)
    pid_file.write_text(str(os.getpid()))


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
    if not best_effort_test_state_write_allowed(
        pid_file, category="axe-lumberjack-pid"
    ):
        return
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
    if data is None or not isinstance(data, dict):
        return None
    status = _dataclass_from_mapping(LumberjackStatus, data)
    if status is None:
        return None
    return _coerce_lumberjack_status(status)


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
    if data is None or not isinstance(data, dict):
        return None
    metrics = _dataclass_from_mapping(LumberjackMetrics, data)
    if metrics is None:
        return None
    return _coerce_lumberjack_metrics(metrics)


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
    if not best_effort_test_state_write_allowed(path, category="axe-log"):
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
    if not best_effort_test_state_write_allowed(root, category="axe-log-maintenance"):
        return 0
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
        if not best_effort_test_state_write_allowed(log_file, category="axe-log"):
            return
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
    if not best_effort_test_state_write_allowed(
        shared_dir, category="axe-shared-state"
    ):
        return shared_dir
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir
