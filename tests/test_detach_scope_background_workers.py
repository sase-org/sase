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
