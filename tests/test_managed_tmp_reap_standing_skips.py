"""Change-only reporting for unsafe-to-reap managed temp entries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import sase.scripts.sase_chop_managed_tmp_reap as chop
from sase.scripts.sase_chop_managed_tmp_reap import _report_standing_skips


class _Log:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.debugs: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)

    def debug(self, message: str) -> None:
        self.debugs.append(message)


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(log=_Log())


def test_same_skip_warns_once_across_three_passes(tmp_path: Path) -> None:
    runtime = _runtime()
    root = tmp_path / "managed"
    entry = root / "agent-tmp" / "held"
    reason = f"entry {entry} preserved because its newest write time is unobservable"
    state = tmp_path / "standing-skips.json"

    for _ in range(3):
        _report_standing_skips(runtime, state, [(root, reason)])

    assert runtime.log.warnings == [f"managed_tmp_reap skipped: {reason}"]
    assert runtime.log.infos == ["managed_tmp_reap: 1 standing skips unchanged"] * 2
    assert len(runtime.log.debugs) == 2


def test_changed_reason_warns_again_and_cleared_skip_logs_once(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    root = tmp_path / "managed"
    entry = root / "agent-tmp" / "held"
    state = tmp_path / "standing-skips.json"
    first = f"entry {entry} preserved because its newest write time is unobservable"
    changed = f"could not fully list entry {entry}"

    _report_standing_skips(runtime, state, [(root, first)])
    _report_standing_skips(runtime, state, [(root, changed)])

    assert runtime.log.warnings == [
        f"managed_tmp_reap skipped: {first}",
        f"managed_tmp_reap skipped: {changed}",
    ]

    _report_standing_skips(runtime, state, [])

    assert len(runtime.log.infos) == 1
    assert "skip cleared:" in runtime.log.infos[0]
    assert str(entry) in runtime.log.infos[0]


def test_corrupt_state_falls_back_to_bounded_warnings(tmp_path: Path) -> None:
    runtime = _runtime()
    root = tmp_path / "managed"
    state = tmp_path / "standing-skips.json"
    state.write_text("not json", encoding="utf-8")
    skips = [(root, f"skip {index}") for index in range(6)]

    _report_standing_skips(runtime, state, skips)

    assert len(runtime.log.warnings) == 5
    assert "skip 0" in runtime.log.warnings[0]
    assert "skip 4" in runtime.log.warnings[-1]
    assert "skip 5" not in " ".join(runtime.log.warnings)
    assert state.read_text(encoding="utf-8") == "not json"


def test_state_is_keyed_by_root_and_entry_and_has_normalized_reason(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    root = tmp_path / "managed"
    entry = root / "agent-tmp" / "held"
    state = tmp_path / "standing-skips.json"

    _report_standing_skips(
        runtime,
        state,
        [
            (
                root,
                f"1234 (systemd, ppid 1): environ unreadable: Permission denied at {entry}",
            )
        ],
    )

    payload = json.loads(state.read_text(encoding="utf-8"))
    records = list(payload["skips"].values())
    assert len(records) == 1
    assert records[0]["root"] == str(root)
    assert records[0]["entry"] == str(entry)
    assert records[0]["reason_class"] == "process environ unreadable"


def test_changing_pid_details_do_not_rewrite_standing_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    root = tmp_path / "managed"
    state = tmp_path / "standing-skips.json"
    writes = Mock(wraps=chop.atomic_write_json)
    monkeypatch.setattr(chop, "atomic_write_json", writes)

    _report_standing_skips(
        runtime,
        state,
        [(root, "1234 (systemd, ppid 1): environ unreadable: Permission denied")],
    )
    _report_standing_skips(
        runtime,
        state,
        [(root, "5678 (systemd, ppid 1): environ unreadable: Permission denied")],
    )

    assert writes.call_count == 1
    assert len(runtime.log.warnings) == 1
