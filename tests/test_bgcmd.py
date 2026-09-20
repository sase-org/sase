"""Tests for the bgcmd module (oneshot-backed background command state)."""

import json
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.bgcmd import (
    BGCMD_STATE_DIR,
    MAX_SLOTS,
    BackgroundCommandInfo,
    choose_bgcmd_slot,
    clear_slot_output,
    dismiss_background_command,
    get_slot_info,
    read_bgcmd_slots,
    read_info_output_tail,
    read_slot_output_tail,
    stop_legacy_background_command,
)
from sase.feature_flags import override_flags
from sase.procs.models import Proc
from sase.procs.service_meta import ProcServiceBlock

_PATCH_READ_PROCS = "sase.procs.read_procs"
_PATCH_DISMISSED = "sase.ace.dismissed_proc_shells.load_dismissed_proc_shells"
_TRANSIENT_ONESHOT = ProcServiceBlock(name=None, mode="oneshot", source="transient")


def _oneshot(
    proc_id: str,
    slot: int | None,
    *,
    command: str = "make test",
    status: str = "running",
    exit_code: int | None = None,
    project: str | None = "myproj",
    workspace_num: int | None = 2,
    started_at: str = "2026-04-23T12:00:00Z",
    finished_at: str | None = None,
    log_path: str = "/tmp/does-not-exist.log",
    service: ProcServiceBlock | None = _TRANSIENT_ONESHOT,
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=command,
        kind="command",
        status=status,
        command=["sh", "-c", command],
        cwd="/ws/2",
        origin="service-proc",
        created_at=started_at,
        log_path=log_path,
        project=project,
        workspace_num=workspace_num,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        pid=4242 if status == "running" else None,
        concurrency_keys=[] if slot is None else [f"bgcmd-slot:{slot}"],
        service=service,
    )


@contextmanager
def _store(procs: list[Proc], *, dismissed: set[str] | None = None) -> Generator[None]:
    with (
        patch(_PATCH_READ_PROCS, return_value=procs),
        patch(_PATCH_DISMISSED, return_value=dismissed or set()),
        override_flags(bgcmd_legacy_slots=False),
    ):
        yield


@contextmanager
def _legacy_dir(*, flag: bool = True) -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        with (
            patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)),
            patch(_PATCH_READ_PROCS, return_value=[]),
            patch(_PATCH_DISMISSED, return_value=set()),
            override_flags(bgcmd_legacy_slots=flag),
        ):
            yield Path(tmp_dir)


def _write_legacy(
    root: Path,
    slot: int,
    *,
    command: str = "make test",
    pid: int | None = None,
    finished_at: str | None = None,
    output: str | None = None,
) -> Path:
    slot_dir = root / str(slot)
    slot_dir.mkdir(parents=True)
    data = {
        "command": command,
        "project": "myproject",
        "workspace_num": 1,
        "workspace_dir": "/path",
        "started_at": "2025-01-01T12:00:00",
        "pid": pid,
        "finished_at": finished_at,
    }
    (slot_dir / "info.json").write_text(json.dumps(data))
    if pid is not None:
        (slot_dir / "pid").write_text(str(pid))
    if output is not None:
        (slot_dir / "output.log").write_text(output)
    return slot_dir


def test_max_slots() -> None:
    assert MAX_SLOTS == 9


def test_background_command_info_dataclass() -> None:
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path/to/workspace",
        started_at="2025-01-01T12:00:00",
    )
    assert info.command == "make test"
    assert info.display_project == "myproject"
    # A bare record is a running legacy slot until proc fields are attached.
    assert info.running is True
    assert info.legacy is True
    assert info.exit_code is None


def test_info_running_follows_proc_status() -> None:
    def make(status: str) -> BackgroundCommandInfo:
        return BackgroundCommandInfo(
            command="c",
            project="p",
            workspace_num=1,
            workspace_dir="/w",
            started_at="t",
            proc_id="proc-1",
            status=status,
        )

    assert all(make(s).running for s in ("pending", "running", "settling"))
    assert not any(make(s).running for s in ("success", "error", "killed", "done"))
    assert make("running").legacy is False


# --- durable oneshot rows -------------------------------------------------


def test_read_bgcmd_slots_maps_oneshot_rows_by_slot_key() -> None:
    running = _oneshot("proc-a", 1, command="pytest -k foo")
    failed = _oneshot(
        "proc-b",
        3,
        command="make lint",
        status="error",
        exit_code=2,
        finished_at="2026-04-23T12:05:00Z",
    )
    with _store([running, failed]):
        infos = read_bgcmd_slots()

    assert sorted(infos) == [1, 3]
    a = infos[1]
    assert (a.command, a.status, a.running, a.legacy) == (
        "pytest -k foo",
        "running",
        True,
        False,
    )
    assert (a.project, a.workspace_num, a.workspace_dir) == ("myproj", 2, "/ws/2")
    assert a.proc_id == "proc-a"
    assert a.pid == 4242
    assert a.finished_at is None
    b = infos[3]
    assert (b.status, b.exit_code, b.running) == ("error", 2, False)
    assert b.finished_at == "2026-04-23T12:05:00Z"


def test_read_bgcmd_slots_ignores_rows_that_are_not_transient_oneshots() -> None:
    daemon = _oneshot(
        "proc-d",
        1,
        service=ProcServiceBlock(name="scheduler", mode="daemon", source="builtin"),
    )
    plain = _oneshot("proc-p", 2, service=None)
    no_slot = _oneshot("proc-n", None)
    with _store([daemon, plain, no_slot]):
        assert read_bgcmd_slots() == {}


def test_read_bgcmd_slots_command_from_non_shell_argv_is_shell_quoted() -> None:
    proc = _oneshot("proc-a", 1)
    proc = Proc(
        **{**proc.__dict__, "argv": ["echo", "a b"], "command": ["echo", "a b"]}
    )
    with _store([proc]):
        assert read_bgcmd_slots()[1].command == "echo 'a b'"


def test_read_bgcmd_slots_project_less_oneshot() -> None:
    proc = _oneshot("proc-a", 1, project=None, workspace_num=None)
    with _store([proc]):
        info = read_bgcmd_slots()[1]
    assert (info.project, info.workspace_num, info.display_project) == ("", 0, "")


def test_newest_finished_row_owns_a_reused_index() -> None:
    newer = _oneshot("new", 1, command="second", status="success", exit_code=0)
    older = _oneshot("old", 1, command="first", status="success", exit_code=0)
    with _store([newer, older]):
        infos = read_bgcmd_slots()
    assert {slot: info.proc_id for slot, info in infos.items()} == {1: "new"}


def test_dismissed_finished_row_is_hidden_and_does_not_resurrect_older_row() -> None:
    newer = _oneshot("new", 1, status="success", exit_code=0)
    older = _oneshot("old", 1, status="success", exit_code=0)
    other = _oneshot("other", 2, status="success", exit_code=0)
    with _store([newer, older, other], dismissed={"new"}):
        infos = read_bgcmd_slots()
    assert {slot: info.proc_id for slot, info in infos.items()} == {2: "other"}


def test_dismissal_never_hides_an_active_row() -> None:
    running = _oneshot("run", 1)
    with _store([running], dismissed={"run"}):
        assert read_bgcmd_slots()[1].proc_id == "run"


def test_active_row_keeps_its_index_over_a_newer_finished_row() -> None:
    finished = _oneshot("done", 1, status="success", exit_code=0)
    running = _oneshot("run", 1)
    with _store([finished, running]):
        infos = read_bgcmd_slots()
    assert {slot: info.proc_id for slot, info in infos.items()} == {1: "run"}


def test_cross_project_active_rows_sharing_an_index_are_both_shown() -> None:
    # The store fences ``bgcmd-slot:<n>`` per project, so two projects can race
    # onto one index; neither running command may vanish.
    newer = _oneshot("newer", 2, project="beta")
    older = _oneshot("older", 2, project="alpha")
    with _store([newer, older]):
        infos = read_bgcmd_slots()
    assert infos[2].proc_id == "newer"
    assert {info.proc_id for info in infos.values()} == {"newer", "older"}
    assert sorted(infos) == [1, 2]


def test_get_slot_info_and_output_tail_for_a_proc_row() -> None:
    proc = _oneshot("proc-a", 4, log_path="/store/logs/a.log")
    with _store([proc]):
        info = get_slot_info(4)
        assert info is not None and info.proc_id == "proc-a"
        assert get_slot_info(5) is None
        with patch("sase.procs.read_proc_log_tail", return_value="line\n") as tail:
            assert read_slot_output_tail(4, 10) == "line\n"
            assert read_slot_output_tail(5, 10) == ""
            assert read_info_output_tail(4, info, 7) == "line\n"
    tail.assert_any_call("proc-a", 7, log_path="/store/logs/a.log")


def test_clear_slot_output_truncates_the_proc_log_and_its_rotation() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        log = Path(tmp_dir) / "a.log"
        rotated = Path(tmp_dir) / "a.log.1"
        log.write_text("current")
        rotated.write_text("older")
        proc = _oneshot("proc-a", 1, log_path=str(log))
        with _store([proc]):
            info = read_bgcmd_slots()[1]
        clear_slot_output(1, info)
        assert log.read_text() == ""
        assert rotated.read_text() == ""


def test_dismiss_records_a_durable_row_without_deleting_it() -> None:
    proc = _oneshot("proc-a", 1, status="success", exit_code=0)
    with _store([proc]):
        info = read_bgcmd_slots()[1]
    with patch(
        "sase.ace.dismissed_proc_shells.record_dismissed_proc_shells",
        return_value=True,
    ) as record:
        assert dismiss_background_command(1, info) is True
    record.assert_called_once_with(["proc-a"])


# --- choosing an index ----------------------------------------------------


def _info(status: str, *, finished: str | None = None, proc: bool = True):
    return BackgroundCommandInfo(
        command="c",
        project="p",
        workspace_num=1,
        workspace_dir="/w",
        started_at="2026-04-23T00:00:00",
        finished_at=finished,
        proc_id="proc" if proc else None,
        status=status,
    )


def test_choose_slot_picks_lowest_free_index() -> None:
    assert choose_bgcmd_slot({}) == 1
    assert choose_bgcmd_slot({1: _info("running"), 3: _info("running")}) == 2


def test_choose_slot_honours_reserved_indices() -> None:
    assert choose_bgcmd_slot({}, reserved={1, 2}) == 3


def test_finished_history_never_blocks_a_new_command() -> None:
    infos = {
        slot: _info("success", finished=f"2026-04-23T00:0{slot}:00")
        for slot in range(1, 10)
    }
    assert choose_bgcmd_slot(infos) == 1
    infos[1] = _info("success", finished="2026-04-23T00:59:00")
    assert choose_bgcmd_slot(infos) == 2


def test_choose_slot_is_none_when_nine_are_running() -> None:
    assert choose_bgcmd_slot({s: _info("running") for s in range(1, 10)}) is None


def test_choose_slot_never_reuses_legacy_directories() -> None:
    infos = {s: _info("done", proc=False) for s in range(1, 10)}
    assert choose_bgcmd_slot(infos) is None
    infos.pop(4)
    assert choose_bgcmd_slot(infos) == 4


# --- legacy slot directories (bgcmd_legacy_slots sunset flag) --------------


def test_bgcmd_state_dir_path() -> None:
    assert isinstance(BGCMD_STATE_DIR, Path)
    assert BGCMD_STATE_DIR.name == "bgcmd"
    assert "axe" in str(BGCMD_STATE_DIR)


def test_legacy_slot_is_readable_while_the_sunset_flag_is_on() -> None:
    with _legacy_dir() as root:
        _write_legacy(root, 2, command="old cmd", finished_at="2025-01-01T12:01:00")
        infos = read_bgcmd_slots()

    info = infos[2]
    assert (info.command, info.legacy, info.running, info.status) == (
        "old cmd",
        True,
        False,
        "done",
    )
    assert info.proc_id is None
    assert info.finished_at == "2025-01-01T12:01:00"


def test_legacy_slots_are_ignored_when_the_sunset_flag_is_off() -> None:
    with _legacy_dir(flag=False) as root:
        _write_legacy(root, 2)
        assert read_bgcmd_slots() == {}
        assert get_slot_info(2) is None


def test_legacy_running_process_is_reported_running() -> None:
    import os

    with _legacy_dir() as root:
        _write_legacy(root, 1, pid=os.getpid())
        info = get_slot_info(1)
    assert info is not None and info.running is True and info.status == "running"


def test_legacy_dead_process_is_marked_finished_on_read() -> None:
    with _legacy_dir() as root:
        slot_dir = _write_legacy(root, 1, pid=99999999)
        info = get_slot_info(1)
        assert info is not None
        assert info.running is False
        assert info.finished_at is not None
        rewritten = json.loads((slot_dir / "info.json").read_text())
    # The legacy file keeps its original schema (no proc-only fields).
    assert set(rewritten) == {
        "command",
        "project",
        "workspace_num",
        "workspace_dir",
        "started_at",
        "pid",
        "finished_at",
    }
    assert rewritten["finished_at"] == info.finished_at


def test_get_slot_info_attaches_display_project_without_persisting_it() -> None:
    with _legacy_dir() as root:
        slot_dir = _write_legacy(root, 1)
        with patch(
            "sase.ace.tui.bgcmd.project_display_name_for", return_value="widgets"
        ):
            info = get_slot_info(1)
        assert "project_display_name" not in json.loads(
            (slot_dir / "info.json").read_text()
        )
    assert info is not None and info.display_project == "widgets"


def test_invalid_or_partial_legacy_info_is_skipped() -> None:
    with _legacy_dir() as root:
        bad = root / "1"
        bad.mkdir()
        (bad / "info.json").write_text("not valid json")
        partial = root / "2"
        partial.mkdir()
        (partial / "info.json").write_text(json.dumps({"command": "make test"}))
        assert read_bgcmd_slots() == {}


def test_a_durable_row_wins_an_index_a_legacy_directory_also_holds() -> None:
    with _legacy_dir() as root:
        _write_legacy(root, 1, command="legacy")
        with patch(
            _PATCH_READ_PROCS,
            return_value=[_oneshot("proc-a", 1, command="durable")],
        ):
            info = get_slot_info(1)
    assert info is not None and info.command == "durable" and not info.legacy


def test_legacy_output_tail_and_clear() -> None:
    with _legacy_dir() as root:
        slot_dir = _write_legacy(root, 1, output="line 1\nline 2\nline 3\n")
        info = get_slot_info(1)
        assert info is not None
        tail = read_info_output_tail(1, info, 2)
        assert "line 1" not in tail and "line 2" in tail and "line 3" in tail
        assert read_slot_output_tail(1, 2) == tail
        clear_slot_output(1, info)
        assert (slot_dir / "output.log").read_text() == ""


def test_legacy_output_helpers_tolerate_missing_files() -> None:
    with _legacy_dir() as root:
        _write_legacy(root, 1)
        info = get_slot_info(1)
        assert info is not None
        assert read_info_output_tail(1, info) == ""
        clear_slot_output(1, info)  # does not raise


def test_dismissing_a_legacy_slot_removes_its_directory() -> None:
    with _legacy_dir() as root:
        slot_dir = _write_legacy(root, 3, output="x")
        info = get_slot_info(3)
        assert info is not None
        assert dismiss_background_command(3, info) is True
        assert not slot_dir.exists()


def test_stopping_a_legacy_slot_signals_its_process_group_and_drops_the_pid() -> None:
    with _legacy_dir() as root:
        slot_dir = _write_legacy(root, 1, pid=4321)
        with (
            patch("sase.ace.tui.bgcmd._is_process_running", return_value=True),
            patch("sase.ace.tui.bgcmd.os.getpgid", return_value=4321),
            patch("sase.ace.tui.bgcmd.os.killpg") as killpg,
        ):
            assert stop_legacy_background_command(1) is True
        killpg.assert_called_once()
        assert not (slot_dir / "pid").exists()


def test_stopping_a_legacy_slot_without_a_pid_is_a_noop() -> None:
    with _legacy_dir() as root:
        _write_legacy(root, 1)
        assert stop_legacy_background_command(1) is False


def test_bgcmd_confirmation_description_uses_display_project() -> None:
    from sase.ace.tui.actions.axe_bgcmd import _bgcmd_description

    info = BackgroundCommandInfo(
        command="make test",
        project="gh_acme__widgets",
        workspace_num=2,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
        project_display_name="widgets",
    )

    description = _bgcmd_description(info)

    assert "(widgets, workspace 2)" in description
    assert "gh_acme__widgets" not in description


def test_bgcmd_confirmation_description_omits_project_for_projectless_oneshot() -> None:
    from sase.ace.tui.actions.axe_bgcmd import _bgcmd_description

    info = BackgroundCommandInfo(
        command="make test",
        project="",
        workspace_num=0,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )

    assert _bgcmd_description(info) == "make test"
