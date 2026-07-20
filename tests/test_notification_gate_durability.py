"""Atomic-write durability coverage for notification-gate files."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sase.notification_gates.durability import atomic_write_json


def test_gate_writer_reaps_only_targeted_stale_temp_siblings(tmp_path: Path) -> None:
    target = tmp_path / "request.json"
    stale = tmp_path / ".request.json.old.tmp"
    fresh = tmp_path / ".request.json.fresh.tmp"
    unrelated = tmp_path / ".response.json.old.tmp"
    for path in (stale, fresh, unrelated):
        path.write_text("temp", encoding="utf-8")
    old = time.time() - 25 * 60 * 60
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))

    atomic_write_json(target, {"ok": True})

    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()
