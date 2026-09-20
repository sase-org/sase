"""End-to-end teardown watchdog tests against real, wedged provider processes.

Each child mimics the incident: it streams its complete reply, gets its final
declaration accepted, and then refuses to exit while a leaked descendant in
its own session holds on.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.declaration_manifest import FINAL_SUBMISSION_FILENAME
from sase.llm_provider import _subprocess_plain as plain
from sase.llm_provider import _subprocess_reap as reap
from sase.llm_provider._subprocess import (
    start_completion_watchdog,
    stream_process_output,
)
from sase.llm_provider._subprocess_stream import stream_json_lines
from sase.llm_provider.muse import MuseProvider

_LEAK_ARGV_MARKER = "leaked-listener-marker"
_HANG_FOREVER = "import time; time.sleep(300)"

# Emits one JSON line naming the leaked descendant, then hangs. The leak runs
# in a new session, out of reach of any process-group signal aimed at the child.
_WEDGED_PROVIDER = textwrap.dedent(
    f"""
    import json, subprocess, sys, time
    leak = subprocess.Popen(
        [sys.executable, "-c", "{_HANG_FOREVER}  # {_LEAK_ARGV_MARKER}"],
        start_new_session=True,
    )
    print(json.dumps({{"reply": "all done", "leak_pid": leak.pid}}), flush=True)
    time.sleep(300)
    """
)


@pytest.fixture(autouse=True)
def _watchdog_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv(plain.TEARDOWN_GRACE_ENV, raising=False)
    # Never consult the developer's real agent registry from a unit test.
    monkeypatch.setattr(reap, "_registered_live_pids", lambda: frozenset())


def _is_running(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _spawn(script: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _accepting_handler(artifacts_dir: Path, leaks: list[int]) -> Callable[[str], None]:
    """Stream handler that plays the host: accept the declaration on the reply."""

    def handle(line: str) -> None:
        event = json.loads(line)
        leaks.append(event["leak_pid"])
        (artifacts_dir / FINAL_SUBMISSION_FILENAME).write_text("{}", encoding="utf-8")

    return handle


def _watch(process: subprocess.Popen[str]) -> None:
    start_completion_watchdog(
        process, runtime="fake", grace_seconds=0.3, poll_seconds=0.02
    )


def test_stream_json_lines_returns_the_reply_of_a_reaped_provider_as_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    leaks: list[int] = []
    process = _spawn(_WEDGED_PROVIDER)
    _watch(process)
    try:
        stderr, return_code = stream_json_lines(
            process, _accepting_handler(tmp_path, leaks), suppress_output=True
        )
    finally:
        if process.poll() is None:
            process.kill()
    leak_pid = leaks[0]

    # The SIGTERM that ended the provider must not read as a failed turn.
    assert return_code == 0
    assert leaks == [leak_pid]
    assert "final declaration was accepted" in stderr
    assert "reaped 1 leaked process(es)" in stderr
    assert not _is_running(leak_pid)

    artifact = json.loads(
        (tmp_path / plain.TEARDOWN_STALL_FILENAME).read_text(encoding="utf-8")
    )
    assert artifact["provider_pid"] == process.pid
    reaped = {item["pid"]: item["argv"] for item in artifact["reaped_descendants"]}
    assert _LEAK_ARGV_MARKER in reaped[leak_pid]
    assert "reaped 1 leaked process(es)" in capsys.readouterr().err


def test_stream_process_output_returns_the_reply_of_a_reaped_provider_as_success(
    tmp_path: Path,
) -> None:
    script = _WEDGED_PROVIDER.replace(
        'print(json.dumps({"reply": "all done", "leak_pid": leak.pid}), flush=True)',
        'print("all done", flush=True)\n'
        f'open({str(tmp_path / FINAL_SUBMISSION_FILENAME)!r}, "w").write("{{}}")',
    )
    process = _spawn(script)
    _watch(process)
    try:
        stdout, stderr, return_code = stream_process_output(
            process, suppress_output=True
        )
    finally:
        if process.poll() is None:
            process.kill()

    assert return_code == 0
    assert stdout == "all done\n"
    assert "final declaration was accepted" in stderr


def test_a_shielded_registered_process_survives_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaks: list[int] = []
    monkeypatch.setattr(reap, "_registered_live_pids", lambda: frozenset(leaks))
    process = _spawn(_WEDGED_PROVIDER)
    _watch(process)
    try:
        _stderr, return_code = stream_json_lines(
            process, _accepting_handler(tmp_path, leaks), suppress_output=True
        )
        # The provider itself is still terminated...
        assert return_code == 0
        assert process.poll() is not None
        # ...but the registered "monitor" it spawned is left alone.
        assert _is_running(leaks[0])
        artifact = json.loads(
            (tmp_path / plain.TEARDOWN_STALL_FILENAME).read_text(encoding="utf-8")
        )
        assert artifact["reaped_descendants"] == []
    finally:
        for pid in leaks:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()


def test_a_provider_that_exits_on_its_own_keeps_its_return_code(
    tmp_path: Path,
) -> None:
    process = _spawn("import sys; print('{}'); sys.exit(3)")
    _watch(process)

    _stderr, return_code = stream_json_lines(
        process, lambda line: None, suppress_output=True
    )

    assert return_code == 3
    assert not (tmp_path / plain.TEARDOWN_STALL_FILENAME).exists()


def test_muse_invoke_survives_a_provider_the_watchdog_had_to_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``_run_subprocess`` caller must not turn SIGTERM into a failed turn."""
    fake_muse = tmp_path / "fake-muse"
    fake_muse.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""
            import json, os, subprocess, sys, time
            subprocess.Popen(
                [sys.executable, "-c", "{_HANG_FOREVER}  # {_LEAK_ARGV_MARKER}"],
                start_new_session=True,
            )
            print(json.dumps({{
                "schema_version": 1, "record_type": "event", "durability": "durable",
                "payload_type": "run.terminal.completed",
                "payload_schema_version": 1,
                "payload": {{"terminal": "completed", "text": "the final reply"}},
            }}), flush=True)
            open(os.path.join(os.environ["SASE_ARTIFACTS_DIR"],
                              "{FINAL_SUBMISSION_FILENAME}"), "w").write("{{}}")
            time.sleep(300)
            """
        ),
        encoding="utf-8",
    )
    fake_muse.chmod(fake_muse.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SASE_MUSE_PATH", str(fake_muse))
    monkeypatch.setenv(plain.TEARDOWN_GRACE_ENV, "0.3")
    # Keep the production 1s poll: the env var only sets the grace period.
    result = _invoke_muse()

    assert result.content == "the final reply"
    artifact = json.loads(
        (tmp_path / plain.TEARDOWN_STALL_FILENAME).read_text(encoding="utf-8")
    )
    assert artifact["runtime"] == "muse"
    assert any(
        _LEAK_ARGV_MARKER in item["argv"] for item in artifact["reaped_descendants"]
    )
    for item in artifact["reaped_descendants"]:
        assert not _is_running(item["pid"])


def _invoke_muse() -> Any:
    from unittest.mock import patch

    with patch("sase.llm_provider.muse.provider_timer"):
        return MuseProvider().invoke("prompt", model_tier="large", suppress_output=True)
