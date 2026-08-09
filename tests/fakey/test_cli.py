from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _environment(state_dir: Path, **values: str) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("FAKEY_")
    }
    env.pop("NO_COLOR", None)
    env.update(FAKEY_STATE_DIR=str(state_dir), **values)
    return env


def _run(
    tmp_path: Path,
    *args: str,
    prompt: str = "test prompt",
    env: dict[str, str] | None = None,
    timeout: float = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sase.fakey.cli", *args],
        input=prompt,
        capture_output=True,
        text=True,
        env=env or _environment(tmp_path),
        timeout=timeout,
        check=False,
    )


def test_default_cli_reply_and_invocation_record(tmp_path: Path) -> None:
    result = _run(tmp_path, "--model", "fakey-large", "--effort", "high", "--internal")

    assert result.returncode == 0
    assert result.stdout == "Fakey completed successfully.\n"
    assert result.stderr == ""
    record = json.loads((tmp_path / "invocation-1.json").read_text())
    assert record["prompt"] == "test prompt"
    assert record["model"] == "fakey-large"
    assert record["effort"] == "high"
    assert record["extra_args"] == ["--internal"]
    assert record["outcome"] == {"exit_code": 0, "status": "succeeded"}


def test_attempt_cursor_persists_across_processes_and_last_repeats(
    tmp_path: Path,
) -> None:
    first = _run(tmp_path, "--scenario", "@flaky")
    second = _run(tmp_path, "--scenario", "@flaky")
    third = _run(tmp_path, "--scenario", "@flaky")

    assert first.returncode == 1
    assert first.stderr == "FAKEY-RETRYABLE: transient fakey failure\n"
    assert second.returncode == 0
    assert second.stdout == "Fakey recovered on the second attempt.\n"
    assert third.returncode == 0
    assert third.stdout == second.stdout
    records = [
        json.loads(path.read_text())
        for path in sorted(tmp_path.glob("invocation-*.json"))
    ]
    assert [record["attempt_index"] for record in records] == [0, 1, 2]


def test_non_retryable_marker_channel_and_exit_code(tmp_path: Path) -> None:
    result = _run(tmp_path, "-s", "@crash")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "FAKEY-FAIL: simulated fakey crash\n"


def test_usage_and_streaming_output(tmp_path: Path) -> None:
    scenario = tmp_path / "usage.yml"
    scenario.write_text(
        "reply: |\n"
        "  first\n"
        "  second\n"
        "stream: {chunk_delay: 0}\n"
        "usage: {input_tokens: 7, output_tokens: 3}\n"
    )

    result = _run(tmp_path / "state", "--scenario", str(scenario))

    assert result.returncode == 0
    assert result.stdout == (
        'first\nsecond\nFAKEY-USAGE: {"input_tokens": 7, "output_tokens": 3}\n'
    )


def test_prompt_block_has_highest_precedence(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        prompt="before\n```fakey\nreply: embedded\n```\nafter",
        env=_environment(tmp_path, FAKEY_REPLY="environment"),
    )

    assert result.stdout == "embedded\n"


def test_explain_does_not_consume_attempt(tmp_path: Path) -> None:
    explained = _run(tmp_path, "--scenario", "@flaky", "--explain")
    assert not list(tmp_path.glob("invocation-*.json"))

    invoked = _run(tmp_path, "--scenario", "@flaky")

    assert explained.returncode == 0
    assert "attempts:" in explained.stdout
    assert invoked.returncode == 1
    record = json.loads((tmp_path / "invocation-1.json").read_text())
    assert record["attempt_index"] == 0


def test_list_scenarios_does_not_read_stdin(tmp_path: Path) -> None:
    result = _run(tmp_path, "--list-scenarios", prompt="")

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "@capacity",
        "@crash",
        "@demo",
        "@flaky",
        "@flaky2",
        "@hang",
        "@ok",
        "@slow",
    ]


def test_help_is_colored_sorted_and_all_long_options_have_aliases(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path, "--help", prompt="", env=_environment(tmp_path, TERM="xterm")
    )

    assert result.returncode == 0
    assert "\033[1;36musage:" in result.stdout
    plain = re.sub(r"\033\[[0-9;]*m", "", result.stdout)
    positions = [
        plain.index(option)
        for option in (
            "--effort",
            "--explain",
            "--help",
            "--list-scenarios",
            "--model",
            "--scenario",
            "--version",
        )
    ]
    assert positions == sorted(positions)
    for alias in ("-e ", "-x,", "-h,", "-l,", "-m ", "-s ", "-v,"):
        assert alias in plain


def test_malformed_scenario_reports_clean_diagnostic(tmp_path: Path) -> None:
    scenario = tmp_path / "broken.yml"
    scenario.write_text("attempts: [\n")

    result = _run(tmp_path / "state", "--scenario", str(scenario))

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("fakey: error: invalid YAML in")
    assert "Traceback" not in result.stderr


def test_barrier_timeout_is_bounded_and_recorded(tmp_path: Path) -> None:
    scenario = tmp_path / "timeout.yml"
    scenario.write_text(
        "steps:\n  - wait_for: {path: /definitely/missing/fakey-file, timeout: 0.05}\n"
    )

    result = _run(tmp_path / "state", "--scenario", str(scenario))

    assert result.returncode == 124
    assert "FAKEY-FAIL: wait_for timed out after 0.05s" in result.stderr
    record = json.loads((tmp_path / "state" / "invocation-1.json").read_text())
    assert record["outcome"]["status"] == "timed_out"


def test_signal_and_wait_for_form_a_deterministic_barrier(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = tmp_path / "started"
    release = tmp_path / "release"
    scenario = tmp_path / "barrier.yml"
    scenario.write_text(
        f"steps:\n  - signal: {started}\n"
        f"  - wait_for: {{path: {release}, timeout: 2}}\n"
        "reply: released\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "sase.fakey.cli", "-s", str(scenario)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(state),
    )
    try:
        assert process.stdin is not None
        process.stdin.write("prompt")
        process.stdin.close()
        deadline = time.monotonic() + 2
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        assert started.exists()
        assert process.poll() is None
        release.touch()
        assert process.wait(timeout=2) == 0
        assert process.stdout is not None
        assert process.stdout.read() == "released\n"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


@pytest.mark.skipif(os.name != "posix", reason="SIGTERM behavior is POSIX-specific")
def test_sigterm_during_barrier_exits_cleanly(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = tmp_path / "started"
    scenario = tmp_path / "terminate.yml"
    scenario.write_text(
        f"steps:\n  - signal: {started}\n"
        f"  - wait_for: {{path: {tmp_path / 'never'}, timeout: 10}}\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "sase.fakey.cli", "-s", str(scenario)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(state),
    )
    try:
        assert process.stdin is not None
        process.stdin.close()
        deadline = time.monotonic() + 2
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        assert started.exists()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=2) == 143
        assert process.stderr is not None
        assert "Traceback" not in process.stderr.read()
        record = json.loads((state / "invocation-1.json").read_text())
        assert record["outcome"]["status"] == "terminated"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
