"""Install validation and one-shot preflight tests for the release watcher."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests._release_watch_helpers import (
    Reader,
    engine,
    fake_process,
    options,
    pr,
    signal_values,
    watch,
)


def inventory_json(
    *,
    host_version: str | None = "0.18.0",
    host_role: str = "host",
    include_host: bool = True,
    plugin_version: str = "0.18.0",
) -> str:
    packages = [
        {
            "name": "sase-plugin-example",
            "role": "plugin",
            "distribution_version": plugin_version,
        }
    ]
    if include_host:
        packages.append(
            {
                "name": "sase",
                "role": host_role,
                "distribution_version": host_version,
            }
        )
    return json.dumps(
        {
            "schema_version": 1,
            "runtime": {
                "executable": "/tmp/venv/bin/sase",
                "python_executable": "/tmp/venv/bin/python",
                "python_version": "3.12.0",
            },
            "packages": packages,
        }
    )


def test_once_preflight_prints_one_state_and_close_argv_without_running_it(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    process, calls = fake_process()
    reader = Reader(signal_values(release=pr()))
    watcher = watch.ReleaseWatcher(
        options(tmp_path, once=True, dry_run=True, close_bead="sase-1kx.3"),
        reader,
        process=process,
        output=output.append,
    )

    code = watcher.run()

    state_lines = [line for line in output if "stage=watch" in line]
    assert code == 0
    assert reader.reads == 1
    assert len(state_lines) == 1
    assert "would dispatch:full_ci" in state_lines[0]
    assert 'close_argv=["sase", "bead", "close", "sase-1kx.3"' in output[1]
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


@pytest.mark.parametrize("use_uv", [True, False])
def test_install_attempt_uses_fresh_venv_and_records_core_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_uv: bool
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if argv[-2:] == ["version", "--json"]:
            stdout = inventory_json()
        elif "importlib.metadata" in argv[-1]:
            stdout = "0.42.1\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(
        engine.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" and use_uv else None,
    )
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.42.1"), Reader(), process=process
    )

    success, detail = watcher.install_attempt(tmp_path / "new-venv")

    assert success
    assert "sase-core-rs=0.42.1" in detail
    assert "sase version --json host distribution_version=0.18.0" in detail
    if use_uv:
        assert commands[0][:2] == ["/usr/bin/uv", "venv"]
        assert commands[1][1:4] == ["pip", "install", "--refresh"]
    else:
        assert commands[0][1:3] == ["-m", "venv"]
        assert commands[1][1:4] == ["-m", "pip", "install"]
    assert commands[2][-2:] == ["version", "--json"]
    assert "--version" not in commands[2]
    assert commands[3][-1].startswith("import importlib.metadata")


@pytest.mark.parametrize(
    ("inventory", "detail"),
    [
        (inventory_json(host_version="0.17.9"), "did not exactly match"),
        (
            inventory_json(host_version="0.17.9", plugin_version="0.18.0"),
            "did not exactly match",
        ),
        ("{malformed", "malformed inventory JSON"),
        (inventory_json(include_host=False), "missing a unique host package row"),
        (inventory_json(host_role="plugin"), "missing a unique host package row"),
        (inventory_json(host_version=None), "missing distribution_version"),
    ],
)
def test_install_attempt_rejects_invalid_host_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inventory: str,
    detail: str,
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        stdout = inventory if argv[-2:] == ["version", "--json"] else "0.42.1\n"
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(engine.shutil, "which", lambda _name: "/usr/bin/uv")
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader(), process=process)

    success, failure = watcher.install_attempt(tmp_path / "new-venv")

    assert not success
    assert detail in failure
    assert commands[2][-2:] == ["version", "--json"]
    assert len(commands) == 3


def test_install_attempt_rejects_core_below_configured_minimum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        stdout = inventory_json() if argv[-2:] == ["version", "--json"] else "0.42.0\n"
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(engine.shutil, "which", lambda _name: "/usr/bin/uv")
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.42.1"), Reader(), process=process
    )

    success, failure = watcher.install_attempt(tmp_path / "new-venv")

    assert not success
    assert (
        "installed sase-core-rs '0.42.0' does not meet required minimum 0.42.1"
        in failure
    )
    assert commands[2][-2:] == ["version", "--json"]
    assert len(commands) == 4


def test_install_attempt_rejects_subprocess_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if argv[-2:] == ["version", "--json"]:
            return subprocess.CompletedProcess(argv, 2, "", "unsupported option")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(engine.shutil, "which", lambda _name: "/usr/bin/uv")
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader(), process=process)

    success, failure = watcher.install_attempt(tmp_path / "new-venv")

    assert not success
    assert "version --json" in failure
    assert "exited 2: unsupported option" in failure
    assert commands[2][-2:] == ["version", "--json"]
    assert len(commands) == 3
