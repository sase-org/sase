"""Retention contract for TUI stall and heartbeat telemetry."""

from __future__ import annotations

import json
from pathlib import Path

from sase.logs import tui_telemetry


def test_stall_log_keeps_recent_rows_and_prunes_rows_older_than_48h(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    now = 2_000_000_000.0
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    monkeypatch.setattr(tui_telemetry.time, "time", lambda: now)
    monkeypatch.setattr(tui_telemetry, "_last_stalls_prune_bucket", None)
    path.write_text(
        "".join(
            json.dumps({"ts": timestamp, "event": event}) + "\n"
            for timestamp, event in (
                (now - 23 * 60 * 60, "within-24h"),
                (now - 47 * 60 * 60, "within-retention"),
                (now - 49 * 60 * 60, "expired"),
            )
        )
    )

    tui_telemetry.log_tui_stall({"ts": now, "event": "current"})

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["event"] for row in rows] == [
        "within-24h",
        "within-retention",
        "current",
    ]
