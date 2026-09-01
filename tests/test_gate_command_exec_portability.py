"""Gate resource opening and command execution without a ``/proc`` filesystem.

The trust model used to reach for ``/proc/self/fd/N`` twice: once to confirm an
owned resource was a regular file, and once as the ``argv[0]`` a verified command
was exec'd through. macOS has no ``/proc``, so every gate creation failed there
with ``owned resource is not a regular file`` and no gate command could ever run.

CI runs on Linux, where ``/proc`` is always present, so these tests force the
no-``/proc`` branch explicitly instead of relying on the host to lack it.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pytest

from sase.notification_gates import command_runner
from sase.notification_gates.command_runner import run_owned_command
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import open_regular_nofollow

_ECHOES_STDIN = "#!/usr/bin/env python3\nimport sys\nprint(sys.stdin.read().strip())\n"


def _command_bundle(root: Path, script: str = _ECHOES_STDIN) -> tuple[Path, str]:
    """Write one executable gate command and return its bundle and hash."""
    commands = root / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    command = commands / "proceed"
    command.write_text(script, encoding="utf-8")
    command.chmod(0o700)
    return root, hashlib.sha256(command.read_bytes()).hexdigest()


@pytest.fixture
def without_proc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the ``/proc`` probe at a path that does not exist."""
    monkeypatch.setattr(command_runner, "_PROC_FD_DIR", tmp_path / "absent" / "fd")


@pytest.mark.usefixtures("without_proc")
def test_owned_command_runs_where_proc_is_absent(tmp_path: Path) -> None:
    """A verified command still executes when no descriptor path is available."""
    bundle, digest = _command_bundle(tmp_path / "bundle")

    completed = run_owned_command(
        bundle,
        ("commands/proceed",),
        expected_hash=digest,
        input_data={"answer": "yes"},
    )

    assert completed.returncode == 0
    assert completed.stdout == b'{"answer":"yes"}\n'


@pytest.mark.usefixtures("without_proc")
def test_streamed_owned_command_runs_where_proc_is_absent(tmp_path: Path) -> None:
    """The streaming path shares the fallback argv, so it runs there too."""
    bundle, digest = _command_bundle(tmp_path / "bundle")
    lines: list[tuple[str, str]] = []

    completed = run_owned_command(
        bundle,
        ("commands/proceed",),
        expected_hash=digest,
        input_data={"answer": "yes"},
        on_output_line=lambda stream, line: lines.append((stream, line)),
    )

    assert completed.returncode == 0
    assert lines == [("stdout", '{"answer":"yes"}')]


@pytest.mark.usefixtures("without_proc")
def test_owned_command_refuses_a_path_swapped_after_hashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exec by path still refuses bytes that replaced the hashed ones.

    Exec'ing ``/proc/self/fd/N`` cannot run anything but the descriptor that was
    hashed. The fallback resolves a path a second time, so it re-checks that the
    path still names that descriptor's inode -- this swaps the file in exactly
    the window between the hash and the spawn.
    """
    bundle, digest = _command_bundle(tmp_path / "bundle")
    command = bundle / "commands" / "proceed"
    replacement = tmp_path / "replacement"
    replacement.write_text("#!/bin/sh\necho pwned\n", encoding="utf-8")
    replacement.chmod(0o700)

    original_sha256_fd = command_runner._sha256_fd

    def swap_after_hashing(fd: int) -> str:
        digest_of_open_file = original_sha256_fd(fd)
        os.replace(replacement, command)
        return digest_of_open_file

    monkeypatch.setattr(command_runner, "_sha256_fd", swap_after_hashing)

    with pytest.raises(GateError) as excinfo:
        run_owned_command(
            bundle, ("commands/proceed",), expected_hash=digest, input_data={}
        )

    assert excinfo.value.code == "hash_mismatch"


def test_exec_target_prefers_the_descriptor_path_where_proc_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Linux keeps exec'ing the descriptor, and keeps it open across the exec."""
    monkeypatch.setattr(command_runner, "_PROC_FD_DIR", tmp_path)

    argv, pass_fds = command_runner._exec_target(7, tmp_path / "unused", ("cmd", "-x"))

    assert argv == ("/proc/self/fd/7", "-x")
    assert pass_fds == (7,)


def test_open_regular_nofollow_accepts_a_regular_file(tmp_path: Path) -> None:
    """The regular-file check reads the descriptor, not a ``/proc`` path."""
    resource = tmp_path / "resource.json"
    resource.write_text("{}", encoding="utf-8")

    fd = open_regular_nofollow(resource)
    try:
        assert os.read(fd, 16) == b"{}"
    finally:
        os.close(fd)


def test_open_regular_nofollow_rejects_a_directory(tmp_path: Path) -> None:
    """A directory is not a regular file wherever the check runs."""
    with pytest.raises(GateError) as excinfo:
        open_regular_nofollow(tmp_path)

    assert excinfo.value.code == "unsafe_file"


def test_open_regular_nofollow_rejects_a_fifo_without_blocking(tmp_path: Path) -> None:
    """A FIFO is refused rather than parking the open until a writer appears.

    Without ``O_NONBLOCK`` this never returns, so the open runs on a worker
    thread and a regression surfaces as a failure instead of a hung suite.
    """
    fifo = tmp_path / "resource.fifo"
    os.mkfifo(fifo)
    outcome: list[BaseException | int] = []

    def open_fifo() -> None:
        try:
            outcome.append(open_regular_nofollow(fifo))
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            outcome.append(exc)

    worker = threading.Thread(target=open_fifo, daemon=True)
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "open_regular_nofollow blocked on a FIFO"
    assert isinstance(outcome[0], GateError)
    assert outcome[0].code == "unsafe_file"
