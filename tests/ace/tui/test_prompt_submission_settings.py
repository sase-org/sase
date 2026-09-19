"""Prompt submission settings parser coverage."""

from __future__ import annotations

from sase.ace.tui.prompt_submission_settings import (
    PromptSubmissionSettings,
    parse_prompt_submission_settings,
)


def test_prompt_submission_settings_default_to_confirm_on_enter() -> None:
    assert parse_prompt_submission_settings({}) == PromptSubmissionSettings(
        confirm_on_enter=True
    )
    assert parse_prompt_submission_settings(None) == PromptSubmissionSettings(
        confirm_on_enter=True
    )
    assert parse_prompt_submission_settings({"prompt_submission": "yes"}) == (
        PromptSubmissionSettings(confirm_on_enter=True)
    )


def test_prompt_submission_settings_accept_valid_false() -> None:
    assert parse_prompt_submission_settings(
        {"prompt_submission": {"confirm_on_enter": False}}
    ) == PromptSubmissionSettings(confirm_on_enter=False)


def test_prompt_submission_settings_reject_non_boolean_values() -> None:
    for value in ("false", 0, 1, None):
        assert parse_prompt_submission_settings(
            {"prompt_submission": {"confirm_on_enter": value}}
        ) == PromptSubmissionSettings(confirm_on_enter=True)
