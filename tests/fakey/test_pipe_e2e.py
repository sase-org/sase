"""End-to-end ``sase pipe`` coverage through the real executor and fakey.

These scenarios exercise the production execution loop, the ``sase pipe``
CLI, follow-up artifact creation, and the ACE agent loader. SIGTERM is
translated into the runner's killed flag rather than targeting pytest's
process group; fakey still runs as a real subprocess.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.axe import runner_signals
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_home
from sase.main.pipe_handler import handle_pipe_command

from tests.fakey.harness import (
    FakeyBarrier,
    FakeyRetryHarness,
    _wait_for_condition,
    successful_attempt,
)

_PIPE_TIMEOUT = 30.0


def _hanging_success(reply: str, barrier: FakeyBarrier) -> dict[str, object]:
    return {
        "succeed": {"reply": reply},
        "steps": barrier.steps(),
    }


def _write_parent_meta(harness: FakeyRetryHarness) -> None:
    meta = {
        "name": "fakey-e2e",
        "pid": 4242,
        "model": "fakey-large",
        "llm_provider": "fakey",
        "workspace_dir": str(harness.workspace),
        "workspace_num": 1,
    }
    (harness.artifacts / "agent_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def _configure_pipe_chain(harness: FakeyRetryHarness, max_chain: int) -> None:
    payload = yaml.safe_load(
        (harness.workspace / "sase.yml").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        payload = {}
    payload["max_agent_pipe_chain"] = max_chain
    (harness.workspace / "sase.yml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _artifact_dirs(harness: FakeyRetryHarness) -> list[Path]:
    return list(
        iter_agent_artifact_dirs(
            harness.project_name,
            newest_first=False,
        )
    )


def _read_meta(artifacts_dir: Path) -> dict[str, Any]:
    return json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))


def _wait_for_named_agent(
    harness: FakeyRetryHarness,
    name: str,
    *,
    timeout: float = _PIPE_TIMEOUT,
) -> Path:
    found: list[Path] = []

    def located() -> bool:
        for path in _artifact_dirs(harness):
            meta_path = path / "agent_meta.json"
            if not meta_path.is_file():
                continue
            try:
                if _read_meta(path).get("name") == name:
                    found.append(path)
                    return True
            except (json.JSONDecodeError, OSError):
                continue
        return False

    _wait_for_condition(located, timeout, f"agent {name!r}")
    return found[-1]


def _pipe(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    prompt: str,
    **kwargs: Any,
) -> int:
    def fake_kill(target: str) -> None:
        assert target == str(artifacts_dir)
        runner_signals._killed_state["killed"] = True
        runner_signals._killed_state["killed_at"] = time.time()
        raise SystemExit(0)

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr(
        "sase.main.pipe_handler.kill_agent_runner_group",
        fake_kill,
    )
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command(prompt, **kwargs)
    return int(exit_info.value.code or 0)


def _resolve_chat_path(chat_path: str) -> Path:
    path = Path(chat_path).expanduser()
    if path.is_file():
        return path
    home_relative = sase_home() / chat_path
    if home_relative.is_file():
        return home_relative
    raise FileNotFoundError(chat_path)


def _load_ace_rows() -> list[Any]:
    result = load_agents_from_disk_with_state(
        set(),
        full_history=True,
        source="pipe-e2e",
    )
    rows: list[Any] = []
    for row in result.all_agents:
        rows.append(row)
        rows.extend(row.followup_agents)
    return rows


def _run_until_hang(
    harness: FakeyRetryHarness,
    barrier: FakeyBarrier,
    monkeypatch: pytest.MonkeyPatch,
    attempts: list[dict[str, object]],
) -> Any:
    _write_parent_meta(harness)
    harness.use_scenario(monkeypatch, attempts)
    handle = harness.run_in_background("Exercise the pipe hand-off.")
    barrier.wait_until_started()
    return handle


def test_default_pipe_creates_family_member_with_fork_and_shared_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        expose_to_agent_loader=True,
    )
    parent_hang = harness.barrier("parent")
    handle = _run_until_hang(
        harness,
        parent_hang,
        monkeypatch,
        [
            _hanging_success("parent waiting to pipe", parent_hang),
            successful_attempt("successor finished"),
        ],
    )
    try:
        assert _pipe(monkeypatch, harness.artifacts, "continue the work") == 0
        parent_hang.open()
        result = handle.finish()
    finally:
        parent_hang.open()
        runner_signals.reset_killed()

    assert result.success is True
    successor_dir = _wait_for_named_agent(harness, "fakey-e2e--1")
    parent_meta = _read_meta(harness.artifacts)
    successor_meta = _read_meta(successor_dir)
    chat = _resolve_chat_path(str(parent_meta["chat_path"])).read_text(encoding="utf-8")
    prompt = (successor_dir / "followup_prompt.md").read_text(encoding="utf-8")

    assert "# Pipe hand-off" in chat
    assert "fakey-e2e--1" in chat
    assert successor_meta["name"] == "fakey-e2e--1"
    assert successor_meta["piped_from"] == "fakey-e2e"
    assert successor_meta["pipe_depth"] == 1
    assert successor_meta["agent_family"] == "fakey-e2e"
    assert successor_meta["workspace_dir"] == parent_meta["workspace_dir"]
    assert successor_meta["workspace_num"] == parent_meta["workspace_num"] == 1
    assert prompt.startswith("#fork:fakey-e2e\n")
    assert prompt.endswith("continue the work")

    rows = _load_ace_rows()
    names = {row.agent_name or row.cl_name for row in rows}
    assert "fakey-e2e--plan" in names
    assert "fakey-e2e--1" in names
    family_rows = [row for row in rows if row.agent_family == "fakey-e2e"]
    assert len(family_rows) >= 2
    workspaces = {row.workspace_dir for row in family_rows if row.workspace_dir}
    assert workspaces == {str(harness.workspace)}


def test_fresh_named_model_pipe_skips_fork_and_records_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        expose_to_agent_loader=True,
    )
    parent_hang = harness.barrier("parent")
    handle = _run_until_hang(
        harness,
        parent_hang,
        monkeypatch,
        [
            _hanging_success("parent waiting to pipe", parent_hang),
            successful_attempt("reviewer finished"),
        ],
    )
    try:
        assert (
            _pipe(
                monkeypatch,
                harness.artifacts,
                "review the result",
                fresh=True,
                model="fakey-small",
                name="review",
                reason="different model and clean context",
            )
            == 0
        )
        parent_hang.open()
        result = handle.finish()
    finally:
        parent_hang.open()
        runner_signals.reset_killed()

    assert result.success is True
    successor_dir = _wait_for_named_agent(harness, "fakey-e2e--review")
    successor_meta = _read_meta(successor_dir)
    prompt = (successor_dir / "followup_prompt.md").read_text(encoding="utf-8")

    assert successor_meta["name"] == "fakey-e2e--review"
    assert successor_meta["agent_family_role"] == "review"
    assert successor_meta["model"] == "fakey-small"
    assert successor_meta["pipe_reason"] == "different model and clean context"
    assert "#fork:" not in prompt
    assert prompt.startswith("%model:fakey-small\n")
    assert prompt.endswith("review the result")

    rows = _load_ace_rows()
    review = next(row for row in rows if row.agent_name == "fakey-e2e--review")
    assert review.model == "fakey-small"


def test_two_link_chain_then_bound_leaves_the_agent_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        expose_to_agent_loader=True,
    )
    _configure_pipe_chain(harness, 2)
    monkeypatch.setattr("sase.main.pipe_handler.get_max_agent_pipe_chain", lambda: 2)
    first_hang = harness.barrier("first")
    second_hang = harness.barrier("second")
    third_hang = harness.barrier("third")
    handle = _run_until_hang(
        harness,
        first_hang,
        monkeypatch,
        [
            _hanging_success("root waiting", first_hang),
            _hanging_success("first successor waiting", second_hang),
            _hanging_success("second successor waiting", third_hang),
            successful_attempt("would not run after the bound"),
        ],
    )
    try:
        assert (
            _pipe(
                monkeypatch,
                harness.artifacts,
                "first hop",
                fresh=True,
                model="fakey-large",
            )
            == 0
        )
        first_hang.open()
        first_successor = _wait_for_named_agent(harness, "fakey-e2e--1")
        first_meta = _read_meta(first_successor)
        assert first_meta["name"] == "fakey-e2e--1"
        assert first_meta["pipe_depth"] == 1
        second_hang.wait_until_started()

        assert (
            _pipe(
                monkeypatch,
                first_successor,
                "second hop",
                fresh=True,
                model="fakey-large",
            )
            == 0
        )
        second_hang.open()
        second_successor = _wait_for_named_agent(harness, "fakey-e2e--2")
        third_hang.wait_until_started()
        assert _read_meta(second_successor)["pipe_depth"] == 2
        assert _read_meta(second_successor)["piped_from"] == "fakey-e2e--1"

        code = _pipe(monkeypatch, second_successor, "should refuse")
        err = capsys.readouterr().err
        assert code == 1
        assert "max_agent_pipe_chain=2" in err
        assert "chain length reached: 2" in err
        assert not (second_successor / ".sase_pipe_pending").exists()
        assert _read_meta(second_successor)["name"] == "fakey-e2e--2"
        assert third_hang.release.exists() is False
        third_hang.open()
        result = handle.finish()
    finally:
        first_hang.open()
        second_hang.open()
        third_hang.open()
        runner_signals.reset_killed()

    assert result.success is True
    assert _read_meta(second_successor)["pipe_depth"] == 2
    assert _read_meta(second_successor)["name"] == "fakey-e2e--2"


def test_monitor_sleep_one_next_still_attaches_and_transfers_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sleep 1 --next`` still uses the shared family-spawn primitive."""
    import os

    import sase.monitor.followup as followup_module
    import sase.procs.spawn as spawn_module
    from sase.agent.launch_types import AgentLaunchResult
    from sase.monitor.output import OutputCapture
    from sase.monitor.start import StartMonitorRequest, start_monitor
    from sase.procs.runtime import proc_started_path, write_json_atomic
    from sase.running_field import WorkspaceClaim

    from tests.monitor._fixtures import make_starter_agent, write_project_file

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        llm_provider="anthropic",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )

    class _FakeSupervisorPid:
        pid = 4242424

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    def fake_popen(*args: object, **kwargs: object) -> _FakeSupervisorPid:
        argv = args[0]
        assert isinstance(argv, list)
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        os.write(
            pass_fds[0], json.dumps({"pid": _FakeSupervisorPid.pid}).encode() + b"\n"
        )
        write_json_atomic(proc_started_path(proc_id), {"pid": _FakeSupervisorPid.pid})
        return _FakeSupervisorPid()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    record = start_monitor(
        StartMonitorRequest(
            command="sleep 1",
            reason="p8.6 spawn regression",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            lane="acme",
            next_action="Report that it finished.",
        )
    )
    (Path(starter_dir) / "done.json").write_text("{}", encoding="utf-8")
    del project_file

    monitor_dir = record.artifacts_dir
    meta = json.loads(
        (Path(monitor_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    capture = OutputCapture()
    capture.append_bytes(b"done\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return AgentLaunchResult(
            pid=999999,
            workspace_num=3,
            workspace_dir=str(tmp_path),
            output_path="/tmp/whatever.txt",
            agent_name="acme--1",
        )

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=2.0,
    )

    assert result.launched is True
    assert captured["workspace_num"] == 3
    assert captured["retry_transfer_from_pid"] == os.getpid()
    assert captured["prompt"].startswith("#fork:acme--0\n")
    env = captured["extra_env"]
    assert env["SASE_INTERNAL_AGENT_NAME_BYPASS"] == "1"
    plan = json.loads(env["SASE_AGENT_FAMILY_ATTACH"])
    assert plan["agent_name"] == "acme--1"
    assert plan["parent_base"] == "acme"
    assert plan["parent_is_running"] is False
