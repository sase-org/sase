"""Full-run transcript file sink for `sase update`."""

from __future__ import annotations

import os
import threading

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .events import OutputSink, StepSpec, StepStatus

_LOG_GLOB = "update-*.log"
_LOG_RETENTION = 20
"""Newest transcript files kept per log directory."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(now: datetime | None = None) -> str:
    return (_utc_now() if now is None else now).strftime("%Y%m%dT%H%M%SZ")


def _default_log_dir() -> Path:
    from sase.core.paths import sase_subdir

    return sase_subdir("logs") / "update"


def _sase_version() -> str:
    try:
        from sase import __version__

        return __version__
    except Exception:  # noqa: BLE001 - best effort only
        return "unknown"


class UpdateLogSink:
    """Append-only plain-text transcript of a full update run.

    Best-effort: any :class:`OSError` while opening or writing disables the
    sink silently. :attr:`path` is the transcript path, or `None` when the
    sink never managed to open its file.
    """

    def __init__(
        self,
        *,
        argv: Sequence[str] = (),
        mode: str = "",
        log_dir: Path | None = None,
        sase_version: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Open ``update-<UTC>-<pid>.log`` and write the run header."""
        self._lock = threading.Lock()
        self._disabled = False
        self._path: Path | None = None
        try:
            directory = log_dir if log_dir is not None else _default_log_dir()
            directory.mkdir(parents=True, exist_ok=True)
            self._path = directory / f"update-{_stamp(now)}-{os.getpid()}.log"
            version = sase_version if sase_version is not None else _sase_version()
            started = (_utc_now() if now is None else now).isoformat()
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write("sase update log\n")
                handle.write(f"argv: {' '.join(argv)}\n")
                handle.write(f"sase: {version}\n")
                if mode:
                    handle.write(f"mode: {mode}\n")
                handle.write(f"started: {started}\n")
                handle.write("---\n")
            self._prune_locked(directory)
        except OSError:
            self._disabled = True
            self._path = None

    @property
    def path(self) -> Path | None:
        """Return the transcript path, or `None` when the sink is disabled."""
        return self._path

    def _prune_locked(self, directory: Path) -> None:
        try:
            files = sorted(directory.glob(_LOG_GLOB), key=lambda p: p.name)
            for stale in files[: max(0, len(files) - _LOG_RETENTION)]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def _write(self, line: str) -> None:
        if self._disabled or self._path is None:
            return
        with self._lock:
            if self._disabled or self._path is None:
                return
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                self._disabled = True

    def declare(self, specs: Sequence[StepSpec]) -> None:
        """Log declared steps."""
        for spec in specs:
            parent = f" parent={spec.parent_id}" if spec.parent_id else ""
            self._write(
                f"[{_utc_now().isoformat()}] DECLARE {spec.id} {spec.title}{parent}\n"
            )

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        """Log a step start."""
        extra = ""
        if title is not None:
            extra += f" {title}"
        if detail is not None:
            extra += f" — {detail}"
        self._write(f"[{_utc_now().isoformat()}] START {id}{extra}\n")

    def output(self, id: str, stream: str, line: str) -> None:
        """Log one output line."""
        self._write(f"[{_utc_now().isoformat()}] OUTPUT {id} {stream}: {line}\n")

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        """Log a step finish."""
        extra = f" — {detail}" if detail is not None else ""
        self._write(f"[{_utc_now().isoformat()}] FINISH {id} {status}{extra}\n")

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        """Log a streamed command line and its working directory."""
        where = f" cwd={cwd}" if cwd else ""
        self._write(
            f"[{_utc_now().isoformat()}] COMMAND {id}{where} {' '.join(argv)}\n"
        )

    def set_mode(self, mode: str) -> None:
        """Record the install mode once it is known."""
        if mode:
            self._write(f"[{_utc_now().isoformat()}] mode: {mode}\n")

    def finalize(
        self,
        status_for_pending: StepStatus = "skipped",
        *,
        status_for_running: StepStatus | None = None,
    ) -> None:
        """Log finalization; per-step lines come from the model's own events."""
        running = (
            status_for_running if status_for_running is not None else status_for_pending
        )
        if running == status_for_pending:
            self._write(f"[{_utc_now().isoformat()}] FINALIZE {status_for_pending}\n")
        else:
            self._write(
                f"[{_utc_now().isoformat()}] FINALIZE {status_for_pending}"
                f" running={running}\n"
            )

    def output_sink(self, id: str) -> OutputSink:
        """Return an :data:`OutputSink` bound to a step."""

        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink
