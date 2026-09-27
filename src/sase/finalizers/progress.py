"""Best-effort controller progress journal for finalizer runs.

The controller process running :func:`sase.finalizers.controller.run_finalizers`
is the single writer of ``<artifacts_dir>/finalizers/progress.jsonl``. The file
is append-only UTF-8 JSONL; every record carries ``v``, ``seq``, ``t`` and
``event`` fields. All I/O and serialization errors are swallowed (logged at
debug) and never change control flow, verdicts, or result bytes.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROGRESS_JOURNAL_FILENAME = "progress.jsonl"
PROGRESS_JOURNAL_DIRNAME = "finalizers"
PROGRESS_JOURNAL_MAX_BYTES = 256 * 1024
PROGRESS_JOURNAL_SCHEMA_VERSION = 1


def _journal_path(artifacts_dir: str | Path) -> Path:
    """Return the journal file path for an artifacts directory."""
    return Path(artifacts_dir) / PROGRESS_JOURNAL_DIRNAME / PROGRESS_JOURNAL_FILENAME


class ProgressJournal:
    """Append-only best-effort JSONL writer owned by the controller process."""

    def __init__(self, artifacts_dir: str | None) -> None:
        self._artifacts_dir = artifacts_dir
        self._next_seq = 1
        self._stopped = False
        if not artifacts_dir:
            self._stopped = True
            return
        try:
            self._next_seq = self._continued_seq(_journal_path(artifacts_dir))
        except Exception:  # noqa: BLE001 - journaling is best-effort
            logger.debug("progress journal seq scan failed", exc_info=True)
            self._stopped = True

    @staticmethod
    def _continued_seq(path: Path) -> int:
        """Return the next sequence number after the records in *path*."""
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 1
        last_seq: int | None = None
        line_count = 0
        for line in raw.splitlines():
            if not line.strip():
                continue
            line_count += 1
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(payload, dict):
                seq = payload.get("seq")
                if isinstance(seq, bool):
                    continue
                if isinstance(seq, int) and seq >= 1:
                    last_seq = seq
                elif isinstance(seq, float) and seq.is_integer() and seq >= 1:
                    last_seq = int(seq)
        if last_seq is not None:
            return last_seq + 1
        return line_count + 1

    @property
    def disabled(self) -> bool:
        """Return whether this journal stopped recording."""
        return self._stopped

    def record(self, event: str, **fields: Any) -> None:
        """Append one ``event`` record; never raises."""
        if self._stopped or not self._artifacts_dir:
            return
        try:
            self._append(event, fields)
        except Exception:  # noqa: BLE001 - journaling is best-effort
            logger.debug("progress journal write failed", exc_info=True)

    def _append(self, event: str, fields: dict[str, Any]) -> None:
        assert self._artifacts_dir is not None
        path = _journal_path(self._artifacts_dir)
        record: dict[str, Any] = {
            "v": PROGRESS_JOURNAL_SCHEMA_VERSION,
            "seq": self._next_seq,
            "t": time.time(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        encoded = line.encode("utf-8")
        try:
            existing = path.stat().st_size if path.is_file() else 0
        except OSError:
            existing = 0
        if existing + len(encoded) > PROGRESS_JOURNAL_MAX_BYTES:
            self._write_truncated(path, existing)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        self._next_seq += 1

    def _write_truncated(self, path: Path, existing: int) -> None:
        """Write the single ``observability_truncated`` record and stop."""
        record = {
            "v": PROGRESS_JOURNAL_SCHEMA_VERSION,
            "seq": self._next_seq,
            "t": time.time(),
            "event": "observability_truncated",
        }
        line = json.dumps(record) + "\n"
        encoded = line.encode("utf-8")
        try:
            if existing + len(encoded) <= PROGRESS_JOURNAL_MAX_BYTES:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                self._next_seq += 1
        except OSError:
            logger.debug("progress journal truncation write failed", exc_info=True)
        finally:
            self._stopped = True


__all__ = [
    "PROGRESS_JOURNAL_DIRNAME",
    "PROGRESS_JOURNAL_FILENAME",
    "PROGRESS_JOURNAL_MAX_BYTES",
    "PROGRESS_JOURNAL_SCHEMA_VERSION",
    "ProgressJournal",
]
