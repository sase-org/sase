"""Tests for runner CLI prompt handoff helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.run_agent_runner_cli import read_prompt_file
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV


def test_read_prompt_file_falls_back_to_persisted_refreshed_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_file = tmp_path / "consumed-prompt.md"
    fallback_file = tmp_path / "submitted_xprompt.md"
    submitted_xprompt = "%n(fix)\nKeep this exact prompt\n"
    fallback_file.write_text(submitted_xprompt, encoding="utf-8")
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")

    assert (
        read_prompt_file(
            str(prompt_file),
            refreshed_fallback_file=str(fallback_file),
        )
        == submitted_xprompt
    )
    assert fallback_file.read_text(encoding="utf-8") == submitted_xprompt


def test_read_prompt_file_does_not_fall_back_without_refresh_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_file = tmp_path / "submitted_xprompt.md"
    fallback_file.write_text("persisted prompt", encoding="utf-8")
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)

    with pytest.raises(FileNotFoundError):
        read_prompt_file(
            str(tmp_path / "missing-prompt.md"),
            refreshed_fallback_file=str(fallback_file),
        )
