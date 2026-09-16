"""Tests for the `sase run` TTY confirm gate on a broad `%hold`."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.feature_flags import override_flags
from sase.main.query_handler._launch import _confirm_hold_arm

pytest.importorskip("sase_core_rs")

_HOLD_PROMPT = "%hold(future, scope=host)\nDo work"


def test_confirm_hold_arm_proceeds_without_a_hold() -> None:
    with patch.dict("os.environ", {}, clear=True):
        assert _confirm_hold_arm(
            "Plain prompt", is_tty_fn=lambda: True, confirm_fn=lambda body: False
        )


def test_confirm_hold_arm_proceeds_for_a_narrow_hold() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert _confirm_hold_arm(
            "%hold:planner\nDo work",
            is_tty_fn=lambda: True,
            confirm_fn=lambda body: False,
        )


def test_confirm_hold_arm_prompts_for_a_broad_hold_on_a_tty() -> None:
    seen: list[str] = []

    def confirm_fn(body: str) -> bool:
        seen.append(body)
        return True

    with (
        patch.dict("os.environ", {}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert _confirm_hold_arm(
            _HOLD_PROMPT, is_tty_fn=lambda: True, confirm_fn=confirm_fn
        )

    assert len(seen) == 1
    assert "scope=host" in seen[0]


def test_confirm_hold_arm_declines_when_user_says_no() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert not _confirm_hold_arm(
            _HOLD_PROMPT, is_tty_fn=lambda: True, confirm_fn=lambda body: False
        )


def test_confirm_hold_arm_skips_prompt_without_a_tty() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert _confirm_hold_arm(
            _HOLD_PROMPT,
            is_tty_fn=lambda: False,
            confirm_fn=lambda body: pytest.fail("must not prompt off a TTY"),
        )


def test_confirm_hold_arm_skips_prompt_inside_a_running_agent() -> None:
    with (
        patch.dict("os.environ", {"SASE_AGENT": "1"}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert _confirm_hold_arm(
            _HOLD_PROMPT,
            is_tty_fn=lambda: True,
            confirm_fn=lambda body: pytest.fail("must not prompt inside an agent"),
        )


def test_confirm_hold_arm_skips_prompt_inside_a_durable_proc() -> None:
    with (
        patch.dict("os.environ", {"SASE_PROC_ID": "proc-1"}, clear=True),
        override_flags(agent_holds=True),
    ):
        assert _confirm_hold_arm(
            _HOLD_PROMPT,
            is_tty_fn=lambda: True,
            confirm_fn=lambda body: pytest.fail("must not prompt inside a proc"),
        )
