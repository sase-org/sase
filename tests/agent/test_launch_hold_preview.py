"""Tests for the broad-`%hold` confirmation predicate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_hold_preview import hold_confirmation_body, prompt_mentions_hold
from sase.feature_flags import override_flags

pytest.importorskip("sase_core_rs")


def test_prompt_mentions_hold_is_a_cheap_substring_check() -> None:
    assert prompt_mentions_hold("%hold:planner\nDo work") is True
    assert prompt_mentions_hold("no directive here") is False


def test_hold_confirmation_body_none_without_hold_marker() -> None:
    assert hold_confirmation_body("Plain prompt, no directives.") is None


def test_hold_confirmation_body_none_for_narrow_named_hold() -> None:
    with override_flags(agent_holds=True):
        body = hold_confirmation_body("%hold:planner\nDo work", project="proj")

    assert body is None


def test_hold_confirmation_body_flags_future_with_host_scope() -> None:
    with override_flags(agent_holds=True):
        body = hold_confirmation_body(
            "%hold(future, scope=host)\nDo work", project="proj"
        )

    assert body is not None
    assert "future" in body
    assert "scope=host" in body


def test_hold_confirmation_body_flags_pending_capture_above_threshold() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir=f"/a/w{i}") for i in range(11)
    ]
    with (
        override_flags(agent_holds=True),
        patch(
            "sase.integrations.agent_list_entries.agent_list_entries",
            return_value=entries,
        ),
    ):
        body = hold_confirmation_body("%hold(pending)\nDo work", project="proj")

    assert body is not None
    assert "captures 11 waiting" in body


def test_hold_confirmation_body_none_for_pending_capture_under_threshold() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
    ]
    with (
        override_flags(agent_holds=True),
        patch(
            "sase.integrations.agent_list_entries.agent_list_entries",
            return_value=entries,
        ),
    ):
        body = hold_confirmation_body("%hold(pending)\nDo work", project="proj")

    assert body is None


def test_hold_confirmation_body_project_scoped_pending_without_project_skips() -> None:
    with override_flags(agent_holds=True):
        body = hold_confirmation_body("%hold(pending)\nDo work", project=None)

    assert body is None


def test_hold_confirmation_body_none_when_flag_disabled() -> None:
    with override_flags(agent_holds=False):
        body = hold_confirmation_body(
            "%hold(future, scope=host)\nDo work", project="proj"
        )

    assert body is None
