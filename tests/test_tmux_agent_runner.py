"""Tests for the tmux-based agent runner."""

import json
from unittest.mock import MagicMock, call, patch

import pytest

from sase.ace.tmux_agent_runner import (
    _capture_pane,
    _map_key,
    _wait_for_stable_content,
    run_tmux_agent_mode,
)


class TestMapKey:
    """Tests for _map_key()."""

    def test_single_char_passes_through(self) -> None:
        assert _map_key("j") == "j"
        assert _map_key("k") == "k"
        assert _map_key("q") == "q"

    def test_named_keys_map_correctly(self) -> None:
        assert _map_key("enter") == "Enter"
        assert _map_key("tab") == "Tab"
        assert _map_key("escape") == "Escape"
        assert _map_key("slash") == "/"

    def test_ctrl_keys_map_correctly(self) -> None:
        assert _map_key("ctrl+d") == "C-d"
        assert _map_key("ctrl+c") == "C-c"

    def test_unknown_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown Textual key"):
            _map_key("nonexistent_key")


class TestCapturePaneMocked:
    """Tests for _capture_pane() with mocked subprocess."""

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    def test_returns_stdout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="screen content\nline 2\n")
        result = _capture_pane("test-session")
        assert result == "screen content\nline 2\n"
        mock_run.assert_called_once_with(
            ["tmux", "capture-pane", "-p", "-t", "test-session"],
            capture_output=True,
            text=True,
            check=True,
        )


class TestWaitForStableContent:
    """Tests for _wait_for_stable_content()."""

    @patch("sase.ace.tmux_agent_runner.time.sleep")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    def test_returns_when_content_stabilizes(
        self, mock_capture: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        # First call returns one thing, next two return the same thing
        mock_capture.side_effect = ["loading...", "stable content", "stable content"]
        result = _wait_for_stable_content(
            "test-session", timeout=5.0, poll_interval=0.1
        )
        assert result == "stable content"

    @patch("sase.ace.tmux_agent_runner.time.monotonic")
    @patch("sase.ace.tmux_agent_runner.time.sleep")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    def test_returns_last_content_on_timeout(
        self,
        mock_capture: MagicMock,
        _mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
    ) -> None:
        # Simulate timeout: time jumps past deadline
        mock_monotonic.side_effect = [0.0, 0.1, 100.0]
        mock_capture.return_value = "changing content"
        result = _wait_for_stable_content("test-session", timeout=1.0)
        assert result == "changing content"


class TestRunTmuxAgentMode:
    """Tests for run_tmux_agent_mode()."""

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_creates_session_with_correct_args(
        self,
        mock_uuid: MagicMock,
        mock_capture: MagicMock,
        mock_wait: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        mock_wait.return_value = "screen"
        mock_capture.return_value = "final screen"

        run_tmux_agent_mode(query="test query", size=(80, 24))

        # Check new-session call
        new_session_call = mock_run.call_args_list[0]
        args = new_session_call[0][0]
        assert args[0:4] == ["tmux", "new-session", "-d", "-s"]
        assert args[4] == "sase-agent-abcdef12"
        assert "-x" in args
        assert "80" in args
        assert "-y" in args
        assert "24" in args

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_sends_keys_in_order(
        self,
        mock_uuid: MagicMock,
        mock_capture: MagicMock,
        mock_wait: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        mock_wait.return_value = "screen"
        mock_capture.return_value = "final screen"
        session = "sase-agent-abcdef12"

        run_tmux_agent_mode(query="test", keys=["j", "j", "enter"])

        # Extract send-keys calls (skip new-session, include before kill-session)
        send_keys_calls = [
            c for c in mock_run.call_args_list if c[0][0][0:2] == ["tmux", "send-keys"]
        ]
        assert len(send_keys_calls) == 3
        assert send_keys_calls[0] == call(
            ["tmux", "send-keys", "-t", session, "j"], check=True
        )
        assert send_keys_calls[1] == call(
            ["tmux", "send-keys", "-t", session, "j"], check=True
        )
        assert send_keys_calls[2] == call(
            ["tmux", "send-keys", "-t", session, "Enter"], check=True
        )

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_returns_json_with_screen(
        self,
        mock_uuid: MagicMock,
        mock_capture: MagicMock,
        mock_wait: MagicMock,
        _mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        mock_wait.return_value = "screen"
        mock_capture.return_value = "final screen content"

        result = run_tmux_agent_mode(query="test")
        parsed = json.loads(result)

        assert parsed["screen"] == "final screen content"
        assert parsed["state"] == {}
        assert parsed["error"] is None

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_kills_session_on_success(
        self,
        mock_uuid: MagicMock,
        mock_capture: MagicMock,
        mock_wait: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        mock_wait.return_value = "screen"
        mock_capture.return_value = "screen"

        run_tmux_agent_mode(query="test")

        # Last call should be kill-session
        kill_call = mock_run.call_args_list[-1]
        assert kill_call == call(
            ["tmux", "kill-session", "-t", "sase-agent-abcdef12"],
            check=False,
        )

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_kills_session_on_error(
        self,
        mock_uuid: MagicMock,
        mock_wait: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        # new-session succeeds, but wait raises
        mock_wait.side_effect = RuntimeError("boom")

        result = run_tmux_agent_mode(query="test")
        parsed = json.loads(result)

        assert parsed["error"] == "boom"
        assert parsed["screen"] == ""

        # kill-session should still be called
        kill_call = mock_run.call_args_list[-1]
        assert kill_call == call(
            ["tmux", "kill-session", "-t", "sase-agent-abcdef12"],
            check=False,
        )

    @patch("sase.ace.tmux_agent_runner.subprocess.run")
    @patch("sase.ace.tmux_agent_runner._wait_for_stable_content")
    @patch("sase.ace.tmux_agent_runner._capture_pane")
    @patch("sase.ace.tmux_agent_runner.uuid.uuid4")
    def test_model_tier_passed_to_command(
        self,
        mock_uuid: MagicMock,
        mock_capture: MagicMock,
        mock_wait: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_uuid.return_value = MagicMock(hex="abcdef1234567890")
        mock_wait.return_value = "screen"
        mock_capture.return_value = "screen"

        run_tmux_agent_mode(query="test", model_tier_override="small")

        # Check inner command includes --model-tier
        new_session_call = mock_run.call_args_list[0]
        inner_cmd = new_session_call[0][0][-1]  # Last arg is the command
        assert "--model-tier small" in inner_cmd
