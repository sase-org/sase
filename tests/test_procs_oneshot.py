"""Tests for transient oneshot service procs (the store behind ``!`` commands)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.bgcmd import read_bgcmd_slots, read_slot_output_tail
from sase.procs import ProcSubmitError, kill_proc, wait_for_proc
from sase.procs.models import Proc
from sase.procs.oneshot import (
    MAX_ONESHOT_SLOTS,
    ONESHOT_ORIGIN,
    _OneshotSlotsExhaustedError,
    choose_oneshot_slot,
    _is_transient_oneshot,
    oneshot_command_text,
    oneshot_display_rows,
    _oneshot_service_block,
    oneshot_shell_argv,
    _oneshot_slot,
    _oneshot_slot_key,
    _proc_occupancy,
    submit_oneshot,
)
from sase.procs.service_meta import SERVICE_ONESHOT_ORIGIN, ProcServiceBlock


def _proc(
    proc_id: str,
    slot: int | None,
    *,
    status: str = "running",
    finished_at: str | None = None,
    keys: list[str] | None = None,
    service: ProcServiceBlock | None = None,
    argv: list[str] | None = None,
) -> Proc:
    argv = argv or ["sh", "-c", "true"]
    return Proc(
        proc_id=proc_id,
        label="l",
        kind="command",
        status=status,
        command=argv,
        argv=argv,
        cwd="/tmp",
        origin="service-proc",
        created_at="2026-04-23T00:00:00Z",
        log_path="/tmp/x.log",
        finished_at=finished_at,
        concurrency_keys=(
            keys
            if keys is not None
            else ([] if slot is None else [f"bgcmd-slot:{slot}"])
        ),
        service=service if service is not None else _oneshot_service_block(),
    )


# --- pure helpers -----------------------------------------------------------


def test_slot_key_round_trips_through_the_row() -> None:
    assert _oneshot_slot_key(4) == "bgcmd-slot:4"
    assert _oneshot_slot(_proc("a", 4)) == 4


@pytest.mark.parametrize(
    "keys",
    [[], ["other:3"], ["bgcmd-slot:0"], ["bgcmd-slot:10"], ["bgcmd-slot:x"]],
)
def test_slot_is_none_without_a_valid_index_key(keys: list[str]) -> None:
    assert _oneshot_slot(_proc("a", None, keys=keys)) is None


def test_only_transient_oneshot_service_blocks_count() -> None:
    assert _is_transient_oneshot(_proc("a", 1))
    daemon = ProcServiceBlock(name="scheduler", mode="daemon", source="builtin")
    assert not _is_transient_oneshot(_proc("a", 1, service=daemon))
    configured = ProcServiceBlock(name=None, mode="oneshot", source="user")
    assert not _is_transient_oneshot(_proc("a", 1, service=configured))
    plain = Proc(**{**_proc("a", 1).__dict__, "service": None})
    assert not _is_transient_oneshot(plain)


def test_command_text_round_trips_shell_strings_and_quotes_other_argv() -> None:
    assert oneshot_command_text(_proc("a", 1, argv=oneshot_shell_argv("a && b"))) == (
        "a && b"
    )
    assert oneshot_command_text(_proc("a", 1, argv=["echo", "a b"])) == "echo 'a b'"


def test_choose_slot_lowest_free_then_oldest_finished() -> None:
    assert choose_oneshot_slot({}) == 1
    assert choose_oneshot_slot({1: (True, "t")}) == 2
    assert choose_oneshot_slot({}, reserved={1}) == 2

    full = dict.fromkeys(range(1, MAX_ONESHOT_SLOTS + 1), (True, "t"))
    assert choose_oneshot_slot(full) is None
    full[5] = (False, "2026-04-23T00:05:00")
    full[7] = (False, "2026-04-23T00:02:00")
    assert choose_oneshot_slot(full) == 7
    assert choose_oneshot_slot(full, reserved={7}) == 5
    assert choose_oneshot_slot(full, reserved={5, 7}) is None


def test_proc_occupancy_uses_finish_time_for_finished_rows() -> None:
    rows = oneshot_display_rows(
        [
            _proc("run", 1),
            _proc("done", 2, status="success", finished_at="2026-04-23T00:09:00Z"),
        ]
    )
    assert _proc_occupancy(rows) == {
        1: (True, "2026-04-23T00:00:00Z"),
        2: (False, "2026-04-23T00:09:00Z"),
    }


def test_display_rows_rehome_the_older_of_two_active_rows_on_one_index() -> None:
    rows = oneshot_display_rows([_proc("new", 1), _proc("old", 1)])
    assert {slot: proc.proc_id for slot, proc in rows.items()} == {1: "new", 2: "old"}


def test_display_rows_drop_an_overflow_row_when_every_index_is_taken() -> None:
    procs = [_proc(f"p{n}", n) for n in range(1, MAX_ONESHOT_SLOTS + 1)]
    rows = oneshot_display_rows([_proc("extra", 1), *procs])
    # The newest active row keeps index 1; the displaced one has nowhere to go.
    assert rows[1].proc_id == "extra"
    assert len(rows) == MAX_ONESHOT_SLOTS


# --- submit_oneshot ---------------------------------------------------------


def _submit(**kwargs: Any) -> tuple[Any, Any]:
    with patch("sase.procs.oneshot.submit_proc_request") as submit:
        submit.return_value = "proc"
        result = submit_oneshot(
            oneshot_shell_argv("make"), label="make", cwd="/ws", **kwargs
        )
    (request,), _ = submit.call_args
    return result, request


def test_oneshot_origin_is_the_shared_service_constant() -> None:
    assert ONESHOT_ORIGIN is SERVICE_ONESHOT_ORIGIN


def test_submit_carries_the_oneshot_service_block_and_slot_key() -> None:
    result, request = _submit(project="proj", workspace_num=3, cl_name="CL", slot=6)

    assert result == "proc"
    assert list(request.argv) == ["sh", "-c", "make"]
    assert request.label == "make"
    assert str(request.cwd) == "/ws"
    assert request.origin == "service-proc"
    assert request.project == "proj"
    assert request.workspace_num == 3
    assert request.cl_name == "CL"
    assert list(request.concurrency_keys) == ["bgcmd-slot:6"]
    assert request.service == ProcServiceBlock(
        name=None, mode="oneshot", source="transient"
    )


def test_submit_without_a_slot_takes_the_lowest_free_index() -> None:
    rows = [_proc("a", 1), _proc("b", 2, status="success")]
    with (
        patch("sase.procs.oneshot.read_procs", return_value=rows),
        patch(
            "sase.ace.dismissed_proc_shells.load_dismissed_proc_shells",
            return_value=set(),
        ),
    ):
        _, request = _submit()
    # Index 2 holds a finished row, but index 3 is free, so history is kept.
    assert list(request.concurrency_keys) == ["bgcmd-slot:3"]


def test_submit_reuses_a_finished_index_when_history_fills_all_nine() -> None:
    rows = [
        _proc(
            f"p{n}",
            n,
            status="success",
            finished_at=f"2026-04-23T00:0{n}:00Z",
        )
        for n in range(1, MAX_ONESHOT_SLOTS + 1)
    ]
    with (
        patch("sase.procs.oneshot.read_procs", return_value=rows),
        patch(
            "sase.ace.dismissed_proc_shells.load_dismissed_proc_shells",
            return_value=set(),
        ),
    ):
        _, request = _submit()
    assert list(request.concurrency_keys) == ["bgcmd-slot:1"]


def test_submit_refuses_a_tenth_active_oneshot() -> None:
    rows = [_proc(f"p{n}", n) for n in range(1, MAX_ONESHOT_SLOTS + 1)]
    with (
        patch("sase.procs.oneshot.read_procs", return_value=rows),
        patch(
            "sase.ace.dismissed_proc_shells.load_dismissed_proc_shells",
            return_value=set(),
        ),
        patch("sase.procs.oneshot.submit_proc_request") as submit,
    ):
        with pytest.raises(_OneshotSlotsExhaustedError, match="9 oneshot slots"):
            submit_oneshot(["true"], label="x", cwd="/ws")
    submit.assert_not_called()
    assert issubclass(_OneshotSlotsExhaustedError, ProcSubmitError)


# --- end to end against a real supervisor -----------------------------------


def test_oneshot_runs_detached_and_records_exit_code_and_output(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", tmp_path / "legacy")

    proc = submit_oneshot(
        oneshot_shell_argv("echo hello; echo oops >&2; exit 3"),
        label="echo hello",
        cwd=tmp_path,
        project="proj",
        workspace_num=2,
    )
    finished = wait_for_proc(proc.proc_id, timeout=15)

    assert finished.status == "error"
    assert finished.exit_code == 3
    assert finished.service == _oneshot_service_block()
    assert finished.concurrency_keys == ["bgcmd-slot:1"]

    infos = read_bgcmd_slots()
    assert sorted(infos) == [1]
    info = infos[1]
    assert (info.command, info.status, info.exit_code) == (
        "echo hello; echo oops >&2; exit 3",
        "error",
        3,
    )
    assert info.running is False
    tail = read_slot_output_tail(1)
    assert "hello" in tail and "oops" in tail


def test_a_finished_oneshot_never_blocks_the_next_and_a_running_one_is_fenced(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", tmp_path / "legacy")

    first = submit_oneshot([sys.executable, "-c", "pass"], label="a", cwd=tmp_path)
    wait_for_proc(first.proc_id, timeout=15)

    # History is not a limit: the finished row keeps #1 visible, next gets #2.
    running = submit_oneshot(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="b",
        cwd=tmp_path,
    )
    try:
        assert running.concurrency_keys == ["bgcmd-slot:2"]
        # Explicitly reusing the running command's index is refused by the store.
        with pytest.raises(ProcSubmitError, match="concurrency"):
            submit_oneshot(["true"], label="c", cwd=tmp_path, slot=2)
        infos = read_bgcmd_slots()
        assert {slot: i.running for slot, i in infos.items()} == {1: False, 2: True}
    finally:
        kill_proc(running.proc_id)
