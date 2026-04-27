"""AttemptRecord and prior-attempt history loading for the Agent model."""

import json
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AttemptRecord:
    """One prior (failed) attempt preserved under ``attempts/<N>/``.

    Mirrors the ``attempt_meta.json`` schema written by
    ``sase.axe.run_agent_exec_attempts.snapshot_attempt``, with the resolved
    paths to the per-attempt reply files.
    """

    attempt_number: int
    status: str  # "failed" or "raised"
    start_epoch: float
    end_epoch: float
    model: str | None
    used_fallback: bool
    error_snippet: str
    error_full: str
    live_reply_path: str
    timestamps_path: str

    def get_reply_content(self) -> str | None:
        """Return the live_reply.md captured for this attempt."""
        try:
            with open(self.live_reply_path, encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, OSError):
            return None

    def get_timestamped_reply_chunks(self) -> list[tuple[str, str]] | None:
        """Return the timestamped chunks captured for this attempt.

        Mirrors ``Agent.get_timestamped_reply_chunks`` shape: list of
        ``(iso_timestamp, content_text)`` or None when the timestamps file
        is missing / empty.
        """
        try:
            with open(self.timestamps_path, encoding="utf-8") as f:
                lines = f.readlines()
        except (FileNotFoundError, OSError):
            return None

        entries: list[tuple[int, str]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append((data["byte_offset"], data["timestamp"]))
            except (json.JSONDecodeError, KeyError):
                continue

        if not entries:
            return None

        try:
            with open(self.live_reply_path, "rb") as f:
                content_bytes = f.read()
        except (FileNotFoundError, OSError):
            return None

        chunks: list[tuple[str, str]] = []
        for i, (offset, ts) in enumerate(entries):
            end = entries[i + 1][0] if i + 1 < len(entries) else len(content_bytes)
            chunks.append(
                (ts, content_bytes[offset:end].decode("utf-8", errors="replace"))
            )

        return chunks if chunks else None

    @property
    def start_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.start_epoch)

    @property
    def end_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.end_epoch)

    @property
    def start_hhmmss(self) -> str:
        return self.start_datetime.strftime("%H:%M:%S")


def load_attempt_history(artifacts_dir: str | None) -> list[AttemptRecord]:
    """Read ``attempts/<N>/attempt_meta.json`` records, sorted by attempt_number.

    Silently tolerates a missing ``attempts/`` directory or malformed meta
    files.
    """
    if not artifacts_dir:
        return []
    attempts_dir = os.path.join(artifacts_dir, "attempts")
    if not os.path.isdir(attempts_dir):
        return []

    records: list[AttemptRecord] = []
    for entry in os.listdir(attempts_dir):
        sub = os.path.join(attempts_dir, entry)
        if not os.path.isdir(sub):
            continue
        meta_path = os.path.join(sub, "attempt_meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        try:
            records.append(
                AttemptRecord(
                    attempt_number=int(data["attempt_number"]),
                    status=str(data.get("status", "failed")),
                    start_epoch=float(data.get("start_epoch", 0.0)),
                    end_epoch=float(data.get("end_epoch", 0.0)),
                    model=data.get("model"),
                    used_fallback=bool(data.get("used_fallback", False)),
                    error_snippet=str(data.get("error_snippet", "")),
                    error_full=str(data.get("error_full", "")),
                    live_reply_path=os.path.join(sub, "live_reply.md"),
                    timestamps_path=os.path.join(sub, "live_reply_timestamps.jsonl"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    records.sort(key=lambda r: r.attempt_number)
    return records
