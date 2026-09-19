"""Typed reader for the ``ace.prompt_submission`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSubmissionSettings:
    """Cached prompt submission behavior settings used by ACE."""

    confirm_on_enter: bool = True


DEFAULT_PROMPT_SUBMISSION_SETTINGS = PromptSubmissionSettings()


def parse_prompt_submission_settings(ace_cfg: object) -> PromptSubmissionSettings:
    """Parse ``ace.prompt_submission`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, a missing or non-mapping ``prompt_submission``
    object, and non-boolean field values all fall back to confirmation enabled.
    """
    if not isinstance(ace_cfg, dict):
        return DEFAULT_PROMPT_SUBMISSION_SETTINGS
    raw = ace_cfg.get("prompt_submission")
    if not isinstance(raw, dict):
        return DEFAULT_PROMPT_SUBMISSION_SETTINGS
    return PromptSubmissionSettings(
        confirm_on_enter=_coerce_bool(raw.get("confirm_on_enter"), default=True),
    )


def _coerce_bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


__all__ = [
    "DEFAULT_PROMPT_SUBMISSION_SETTINGS",
    "PromptSubmissionSettings",
    "parse_prompt_submission_settings",
]
