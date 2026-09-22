"""Tests for ``sase tui --tmux`` window claiming and session selection."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest

from sase.main import ace_tmux
from tests.main.ace_tmux_helpers import (
    FakeTmux,
    completed_process,
    launch_args,
    patch_screenshot_request_dir,
)


@pytest.fixture(autouse=True)
def _sandbox_screenshot_request_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_screenshot_request_dir(monkeypatch, tmp_path)


def test_returns_sase_tmux_1_on_fresh_session(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui", "my-query"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_1" in out
    assert "sase_tmux_session=agent-session-7" in out
    assert "sase_tmux_target=@1" in out
    assert "sase_tmux_window_id=@1" in out
    assert "sase_screenshot_dir=" in out
    # The PID reported must be the fake pane pid (first window → base + 1),
    # not the parent process's PID. This locks in that we surface the child.
    assert f"sase_tmux_pid={fake.pane_pid_base + 1}" in out


def test_skips_occupied_window_numbers(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True, existing_windows=("sase_tmux_1",))
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_2" in out
    new_window_calls = [c for c in fake.calls if c[1] == "new-window"]
    assert len(new_window_calls) == 1
    assert (new_window_calls[0][new_window_calls[0].index("-n") + 1]).startswith(
        "sase_tmux_2_"
    )


def test_claim_window_uses_local_claim_when_tmux_allows_duplicate_names(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)

    first = ace_tmux._claim_window("agent-session-7", "sleep 60", runner=fake)
    second = ace_tmux._claim_window("agent-session-7", "sleep 60", runner=fake)

    assert first.window_name == "sase_tmux_1"
    assert second.window_name == "sase_tmux_2"
    assert first.target == "@1"
    assert second.target == "@2"
    assert first.screenshot_dir != second.screenshot_dir


def test_inside_tmux_uses_current_session(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True, session_name="my-session")
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == "my-session:"
    # We should NOT have created or checked for the agents session.
    assert not any(c[1] == "has-session" for c in fake.calls)
    assert not any(c[1] == "new-session" for c in fake.calls)


def test_outside_tmux_creates_agents_session(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    fake = FakeTmux(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    assert any(
        c[1] == "has-session" and ace_tmux._AGENTS_SESSION in c for c in fake.calls
    )
    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == f"{ace_tmux._AGENTS_SESSION}:"


def test_outside_tmux_creates_session_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)

    class _FakeNoSession(FakeTmux):
        def __call__(
            self, cmd: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            self.calls.append(list(cmd))
            if cmd[1] == "has-session":
                return completed_process(cmd, returncode=1, stderr="no such session\n")
            return super().__call__(cmd, **kwargs)

    fake = _FakeNoSession(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    assert any(c[1] == "new-session" for c in fake.calls)


def test_exits_with_message_when_tmux_missing(capsys) -> None:
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value=None),
        pytest.raises(SystemExit) as excinfo,
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "tmux executable not found" in err
