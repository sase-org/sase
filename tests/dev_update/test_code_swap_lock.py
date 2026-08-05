"""Tests for the editable source-tree code-swap lock."""

from __future__ import annotations

import json
import os

from sase.core.paths import sase_subdir
from sase.dev_update import code_swap_lock as lock_mod
from sase.dev_update.code_swap_lock import (
    ENV_DISABLE_CODE_SWAP_LOCK,
    code_swap_advisory_reader_lock,
    code_swap_advisory_warning,
    code_swap_reader_lock,
    code_swap_readers_active,
    code_swap_writer_lock,
)


def test_reader_acquires_and_registers_holder() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ) as lock:
        assert lock.acquired is True
        active = code_swap_readers_active()
        assert active is not None
        assert "sase bead work" in active
        assert f"pid {os.getpid()}" in active
        assert "sase bead work plan.md" in active

    assert code_swap_readers_active() is None


def test_writer_is_refused_while_reader_holds_lock() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ) as reader:
        assert reader.acquired is True
        with code_swap_writer_lock() as writer:
            assert writer.acquired is False
            assert writer.blocked_by is not None
            assert "sase bead work" in writer.blocked_by
            assert "plan.md" in writer.blocked_by


def test_reader_is_refused_while_writer_holds_lock() -> None:
    with code_swap_writer_lock() as writer:
        assert writer.acquired is True
        with code_swap_reader_lock(
            op="bead.work",
            command=("sase", "bead", "work", "plan.md"),
        ) as reader:
            assert reader.acquired is False
            assert reader.blocked_by is not None
            assert "sase dev update" in reader.blocked_by


def test_two_readers_can_hold_lock_together() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "one.md"),
    ) as first:
        with code_swap_reader_lock(
            op="bead.work",
            command=("sase", "bead", "work", "two.md"),
        ) as second:
            assert first.acquired is True
            assert second.acquired is True


def test_dead_holder_sidecar_is_ignored(monkeypatch) -> None:
    holders_dir = sase_subdir("locks") / "code-swap.holders"
    holders_dir.mkdir(parents=True, exist_ok=True)
    holder_path = holders_dir / "424242.json"
    holder_path.write_text(
        json.dumps(
            {
                "pid": 424242,
                "op": "bead.work",
                "command": ["sase", "bead", "work", "dead.md"],
                "started_at": "2026-08-02T12:00:00+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lock_mod, "is_process_running", lambda _pid: False)

    assert code_swap_readers_active() is None
    assert not holder_path.exists()
    with code_swap_writer_lock() as writer:
        assert writer.acquired is True


def test_disable_env_var_makes_locks_noops(monkeypatch) -> None:
    monkeypatch.setenv(ENV_DISABLE_CODE_SWAP_LOCK, "1")

    with code_swap_writer_lock() as writer:
        with code_swap_reader_lock(
            op="bead.work",
            command=("sase", "bead", "work", "plan.md"),
        ) as reader:
            assert writer.acquired is True
            assert reader.acquired is True

    assert code_swap_readers_active() is None


def test_advisory_reader_never_blocks_writer_lock() -> None:
    with code_swap_advisory_reader_lock(
        op="agent.runner",
        command=("bbugyi200.athena.tg",),
    ):
        with code_swap_writer_lock() as writer:
            assert writer.acquired is True


def test_readers_active_ignores_advisory_holders() -> None:
    with code_swap_advisory_reader_lock(
        op="agent.runner",
        command=("bbugyi200.athena.tg",),
    ):
        assert code_swap_readers_active() is None


def test_advisory_warning_lists_live_advisory_holders(monkeypatch) -> None:
    assert code_swap_advisory_warning() is None

    with code_swap_advisory_reader_lock(op="agent.runner", command=("tg",)):
        warning = code_swap_advisory_warning()
        assert warning is not None
        assert "1 agent runner(s)" in warning

        holders_dir = sase_subdir("locks") / "code-swap.holders"
        other_holder_path = holders_dir / "424243.advisory.json"
        other_holder_path.write_text(
            json.dumps(
                {
                    "pid": 424243,
                    "op": "agent.runner",
                    "command": ["tg2"],
                    "started_at": "2026-08-05T12:00:00+00:00",
                    "blocking": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        real_is_running = lock_mod.is_process_running
        monkeypatch.setattr(
            lock_mod,
            "is_process_running",
            lambda pid: True if pid == 424243 else real_is_running(pid),
        )

        warning = code_swap_advisory_warning()
        assert warning is not None
        assert "2 agent runner(s)" in warning
        other_holder_path.unlink()

    assert code_swap_advisory_warning() is None


def test_advisory_warning_disabled_by_env_var(monkeypatch) -> None:
    with code_swap_advisory_reader_lock(op="agent.runner", command=("tg",)):
        monkeypatch.setenv(ENV_DISABLE_CODE_SWAP_LOCK, "1")
        assert code_swap_advisory_warning() is None


def test_advisory_reader_still_removed_from_a_dead_pid(monkeypatch) -> None:
    holders_dir = sase_subdir("locks") / "code-swap.holders"
    holders_dir.mkdir(parents=True, exist_ok=True)
    holder_path = holders_dir / "424242.advisory.json"
    holder_path.write_text(
        json.dumps(
            {
                "pid": 424242,
                "op": "agent.runner",
                "command": ["tg"],
                "started_at": "2026-08-02T12:00:00+00:00",
                "blocking": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lock_mod, "is_process_running", lambda _pid: False)

    assert code_swap_advisory_warning() is None
    assert not holder_path.exists()
