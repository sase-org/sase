"""Tests for repeat-chain STOP detection (`sase.axe.run_agent_repeat_stop`)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.repeat_launcher import REPEAT_PREV_NAME_ENV
from sase.axe.run_agent_repeat_stop import (
    RepeatStopDecision,
    detect_repeat_stop,
    is_stop_value,
)


class TestIsStopValue:
    @pytest.mark.parametrize(
        "value",
        ["", "0", "false", "False", "FALSE", "no", "No", "off", "OFF", "  off  "],
    )
    def test_falsy_values(self, value: str) -> None:
        assert is_stop_value(value) is False

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "yes", "on", "stop", "anything", "2"],
    )
    def test_truthy_values(self, value: str) -> None:
        assert is_stop_value(value) is True


class TestDetectRepeatStop:
    def test_noop_when_prev_name_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REPEAT_PREV_NAME_ENV, raising=False)
        assert detect_repeat_stop() is None

    def test_noop_when_predecessor_unresolvable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(REPEAT_PREV_NAME_ENV, "foo.1")
        with patch(
            "sase.agent.output_variable_context.read_waited_agent_output_variables",
            return_value=None,
        ):
            assert detect_repeat_stop() is None

    def test_noop_when_no_stop_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REPEAT_PREV_NAME_ENV, "foo.1")
        with patch(
            "sase.agent.output_variable_context.read_waited_agent_output_variables",
            return_value={"other": "value"},
        ):
            assert detect_repeat_stop() is None

    def test_noop_when_stop_is_falsy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REPEAT_PREV_NAME_ENV, "foo.1")
        with patch(
            "sase.agent.output_variable_context.read_waited_agent_output_variables",
            return_value={"STOP": "0"},
        ):
            assert detect_repeat_stop() is None

    def test_stop_returns_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REPEAT_PREV_NAME_ENV, "foo.2")
        with patch(
            "sase.agent.output_variable_context.read_waited_agent_output_variables",
            return_value={"STOP": "1"},
        ):
            decision = detect_repeat_stop()

        assert decision == RepeatStopDecision(producer_name="foo.2", stop_value="1")

    def test_stop_preserves_raw_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REPEAT_PREV_NAME_ENV, "foo.2")
        with patch(
            "sase.agent.output_variable_context.read_waited_agent_output_variables",
            return_value={"STOP": "done"},
        ):
            decision = detect_repeat_stop()

        assert decision is not None
        assert decision.stop_value == "done"
