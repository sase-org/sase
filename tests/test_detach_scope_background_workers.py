"""Hook, chat-install, and SDD background workers escape the service cgroup.

Scheduler routines and the Telegram receiver run inside ``sase.service``; the
detached helpers they spawn (hook runs, the chat-install update worker, and
the file-hook batch runner and async bead sync worker behind every SDD commit)
must survive a ``KillMode=mixed`` host stop or restart.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.bead._sync_publication import AsyncPushHandle
from sase.detach_scope import _DetachScopeCommand
from tests._detach_scope_helpers import escaped_launch, fake_popen_class, noop_launch

_Launch = Callable[[list[str]], _DetachScopeCommand]


def test_hook_execution_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.hooks.execution as execution_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    output_path = tmp_path / "hook.txt"
    monkeypatch.setattr(execution_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        execution_module.subprocess, "Popen", fake_popen_class(captured, pid=4326)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr(
        execution_module, "get_hook_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(execution_module, "generate_timestamp", lambda: "260921_120000")

    patch = _types.SimpleNamespace(name="cl1")
    hook = _types.SimpleNamespace(
        run_command="echo hi",
        display_command="echo hi",
        command="echo hi",
        status_lines=[],
    )
    updated, returned_path = execution_module.start_hook_background(
        patch, hook, str(tmp_path), "entry1"
    )

    assert returned_path == str(output_path)
    assert updated.status_lines[-1].suffix == "4326"
    assert captured["detach_kwargs"] == {
        "description": "SASE hook runner",
        "unit_prefix": "sase-hook",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_hook_execution_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.hooks.execution as execution_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    output_path = tmp_path / "hook.txt"
    monkeypatch.setattr(execution_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        execution_module.subprocess, "Popen", fake_popen_class(captured, pid=4326)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr(
        execution_module, "get_hook_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(execution_module, "generate_timestamp", lambda: "260921_120000")

    patch = _types.SimpleNamespace(name="cl1")
    hook = _types.SimpleNamespace(
        run_command="echo hi",
        display_command="echo hi",
        command="echo hi",
        status_lines=[],
    )
    _, returned_path = execution_module.start_hook_background(
        patch, hook, str(tmp_path), "entry1"
    )

    assert returned_path == str(output_path)
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_chat_install_worker_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.integrations import chat_install as chat_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    state_dir = tmp_path / "chat_install"
    monkeypatch.setattr(chat_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(chat_module, "_STATE_DIR", state_dir)
    monkeypatch.setattr(chat_module, "_LOCK_PATH", state_dir / "install.lock")
    monkeypatch.setattr(chat_module, "_LOG_DIR", state_dir / "logs")
    monkeypatch.setattr(chat_module, "_COMPLETIONS_DIR", state_dir / "completions")
    monkeypatch.setattr(chat_module, "_JOBS_DIR", state_dir / "jobs")
    monkeypatch.setattr(
        chat_module.subprocess,
        "Popen",
        fake_popen_class(captured, pid=4327),
    )

    result = chat_module.start_chat_install_worker()

    assert result.status == "launched"
    assert result.pid == 4327
    assert captured["detach_kwargs"] == {
        "description": "SASE chat-install worker",
        "unit_prefix": "sase-chat-install",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False
    assert popen_kwargs["pass_fds"]
    assert popen_kwargs["env"][chat_module._LOCK_FD_ENV] == str(  # noqa: SLF001
        popen_kwargs["pass_fds"][0]
    )


def test_chat_install_worker_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.integrations import chat_install as chat_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    state_dir = tmp_path / "chat_install"
    monkeypatch.setattr(chat_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(chat_module, "_STATE_DIR", state_dir)
    monkeypatch.setattr(chat_module, "_LOCK_PATH", state_dir / "install.lock")
    monkeypatch.setattr(chat_module, "_LOG_DIR", state_dir / "logs")
    monkeypatch.setattr(chat_module, "_COMPLETIONS_DIR", state_dir / "completions")
    monkeypatch.setattr(chat_module, "_JOBS_DIR", state_dir / "jobs")
    monkeypatch.setattr(
        chat_module.subprocess,
        "Popen",
        fake_popen_class(captured, pid=4327),
    )

    result = chat_module.start_chat_install_worker()

    assert result.status == "launched"
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True
    assert popen_kwargs["pass_fds"]


def _spawn_file_hook_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: _Launch,
) -> dict[str, object]:
    import sase.file_hooks.dispatch as dispatch_module

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    def fake_popen(argv: list[str], **kwargs: object) -> object:
        captured["popen_argv"] = list(argv)
        captured["popen_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(dispatch_module, "detach_scope", fake_detach_scope)
    batch_path = tmp_path / "batch.json"
    dispatch_module._spawn_batch(  # noqa: SLF001
        batch_path=batch_path,
        batch_id="batch-1",
        repo_root=str(tmp_path),
        popen=fake_popen,  # type: ignore[arg-type]
    )
    return captured


def test_file_hook_batch_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _spawn_file_hook_batch(monkeypatch, tmp_path, escaped_launch)

    assert captured["detach_argv"] == [
        sys.executable,
        "-m",
        "sase",
        "file-hook",
        "exec-batch",
        str(tmp_path / "batch.json"),
    ]
    assert captured["detach_kwargs"] == {
        "description": "SASE file-hook batch runner",
        "unit_prefix": "sase-file-hook",
    }
    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert captured["popen_argv"] == ["scope", *detach_argv]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_file_hook_batch_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _spawn_file_hook_batch(monkeypatch, tmp_path, noop_launch)

    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def _start_async_bead_push(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: _Launch,
) -> tuple[dict[str, object], AsyncPushHandle | None]:
    import sase.bead._sync_publication as publication_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            captured["popen_argv"] = list(argv)
            captured["popen_kwargs"] = kwargs
            self.pid = 4330

    monkeypatch.setattr(publication_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(publication_module, "has_push_remote", lambda _root: True)
    monkeypatch.setattr(publication_module.subprocess, "Popen", FakePopen)
    log_path = tmp_path / "sync.log"
    handle = publication_module.push_bead_work_launch_async(
        tmp_path,
        find_git_root=lambda _path: tmp_path,
        new_sync_log_path=lambda: log_path,
    )
    return captured, handle


def test_async_bead_push_worker_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured, handle = _start_async_bead_push(monkeypatch, tmp_path, escaped_launch)

    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert detach_argv[:3] == [sys.executable, "-m", "sase.bead.sync_worker"]
    assert captured["detach_kwargs"] == {
        "description": "SASE bead sync worker",
        "unit_prefix": "sase-bead-sync",
    }
    assert captured["popen_argv"] == ["scope", *detach_argv]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False
    # systemd-run --scope execs in place, so the recorded pid is the worker's.
    assert handle is not None and handle.pid == 4330


def test_async_bead_push_worker_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured, handle = _start_async_bead_push(monkeypatch, tmp_path, noop_launch)

    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True
    assert handle is not None


def _delete_trash_in_background(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: _Launch,
) -> dict[str, object]:
    import sase._linked_repo_workspaces as trash_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    monkeypatch.setattr(trash_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        trash_module.subprocess, "Popen", fake_popen_class(captured, pid=4340)
    )
    trash_module._delete_paths_in_background(  # noqa: SLF001
        [tmp_path / "clone.sase-reclone-trash-abc123"]
    )
    return captured


def test_trash_delete_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _delete_trash_in_background(monkeypatch, tmp_path, escaped_launch)

    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert detach_argv[0] == sys.executable
    assert detach_argv[1] == "-c"
    assert captured["detach_kwargs"] == {
        "description": "SASE trash background delete",
        "unit_prefix": "sase-trash-delete",
    }
    assert captured["popen_argv"] == ["scope", *detach_argv]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_trash_delete_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _delete_trash_in_background(monkeypatch, tmp_path, noop_launch)

    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def _spawn_goal_fetch_worker(
    monkeypatch: pytest.MonkeyPatch,
    launch: _Launch,
) -> dict[str, object]:
    import sase.goals.fetch_worker as fetch_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    monkeypatch.setattr("sase.detach_scope.detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        fetch_module.subprocess, "Popen", fake_popen_class(captured, pid=4341)
    )
    assert fetch_module.spawn_fetch_worker("proj") is True
    return captured


def test_goal_fetch_worker_uses_detach_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spawn_goal_fetch_worker(monkeypatch, escaped_launch)

    assert captured["detach_argv"] == [
        sys.executable,
        "-m",
        "sase.goals.fetch_worker",
        "proj",
    ]
    assert captured["detach_kwargs"] == {
        "description": "SASE goal fetch worker",
        "unit_prefix": "sase-goal-fetch",
    }
    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert captured["popen_argv"] == ["scope", *detach_argv]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_goal_fetch_worker_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _spawn_goal_fetch_worker(monkeypatch, noop_launch)

    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_goal_fast_path_uses_shared_fetch_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.goals.fetch_worker as fetch_module
    import sase.main.goal_fast_path as fast_path_module

    calls: list[str] = []
    monkeypatch.setattr(
        fetch_module,
        "spawn_fetch_worker",
        lambda project: calls.append(project) or True,
    )
    fast_path_module._spawn_fetch_worker("proj")  # noqa: SLF001

    assert calls == ["proj"]


def _start_federation_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: _Launch,
) -> dict[str, object]:
    import types as _types

    import sase.dispatch.federation._supervisor as supervisor_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    monkeypatch.setattr("sase.detach_scope.detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        supervisor_module.FederationWorkerSupervisor,
        "_healthy",
        lambda self, **kwargs: False,
    )
    monkeypatch.setattr(
        supervisor_module.FederationWorkerSupervisor,
        "_wait_for_health",
        lambda self, timeout: None,
    )
    monkeypatch.setattr(
        supervisor_module.FederationWorkerSupervisor,
        "_ensure_configured",
        lambda self, timeout: None,
    )
    settings = _types.SimpleNamespace(
        sase_home=tmp_path,
        resolved_socket_path=tmp_path / "worker.sock",
        idle_timeout_seconds=3,
        max_frame_bytes=1024,
        run_root=None,
    )
    supervisor = supervisor_module.FederationWorkerSupervisor(
        config=_types.SimpleNamespace(worker=settings),
        command_resolver=lambda _settings: ("worker-bin",),
        popen=fake_popen_class(captured, pid=4342),
    )
    supervisor.ensure_started(1)
    return captured


def test_federation_worker_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _start_federation_worker(monkeypatch, tmp_path, escaped_launch)

    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert detach_argv[:1] == ["worker-bin"]
    assert captured["detach_kwargs"] == {
        "description": "SASE federation worker",
        "unit_prefix": "sase-federation",
    }
    assert captured["popen_argv"] == ["scope", *detach_argv]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_federation_worker_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _start_federation_worker(monkeypatch, tmp_path, noop_launch)

    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def _bootstrap_tmux_session(
    monkeypatch: pytest.MonkeyPatch,
    launch: _Launch,
) -> tuple[dict[str, object], dict[str, object]]:
    import subprocess as _subprocess

    import sase.main.ace_tmux_session as session_module

    captured: dict[str, object] = {}
    calls: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return launch(list(argv))

    def fake_run_command(
        cmd: list[str], **kwargs: object
    ) -> _subprocess.CompletedProcess[str]:
        calls["argv"] = list(cmd)
        calls["kwargs"] = dict(kwargs)
        session = cmd[cmd.index("-s") + 1]
        name = cmd[cmd.index("-n") + 1]
        return _subprocess.CompletedProcess(cmd, 0, f"{session}\t@7\t{name}\n", "")

    monkeypatch.setattr(session_module, "detach_scope", fake_detach_scope)
    resolved = session_module._create_agents_tmux_session_with_bootstrap(  # noqa: SLF001
        runner=_subprocess.run,
        timeout=None,
        run_command=fake_run_command,  # type: ignore[arg-type]
    )
    assert resolved.session
    assert resolved.bootstrap_window is not None
    return captured, calls


def test_tmux_bootstrap_uses_detach_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, calls = _bootstrap_tmux_session(monkeypatch, escaped_launch)

    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert detach_argv[:3] == ["tmux", "new-session", "-d"]
    assert "-P" in detach_argv and "-F" in detach_argv
    assert captured["detach_kwargs"] == {
        "description": "SASE agents tmux session bootstrap",
        "unit_prefix": "sase-tmux",
    }
    assert calls["argv"] == ["scope", *detach_argv]
    run_kwargs = calls["kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["start_new_session"] is False


def test_tmux_bootstrap_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured, calls = _bootstrap_tmux_session(monkeypatch, noop_launch)

    assert calls["argv"] == captured["detach_argv"]
    run_kwargs = calls["kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["start_new_session"] is True
