"""Tests for ``sase init skills`` generated target paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import _get_target_path, _get_target_paths


def test_get_target_path_claude_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude deploys to ~/.claude/skills/<name>/SKILL.md."""
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    target = _get_target_path("claude", "foo", use_chezmoi=False)
    assert target == Path("/home/u/.claude/skills/foo/SKILL.md")


def test_get_target_path_claude_chezmoi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude under chezmoi deploys to <CHEZMOI_HOME>/dot_claude/skills/..."""
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", Path("/c/home"))
    target = _get_target_path("claude", "foo", use_chezmoi=True)
    assert target == Path("/c/home/dot_claude/skills/foo/SKILL.md")


def test_get_target_paths_agy_single_antigravity_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antigravity deploys to a single ~/.gemini/antigravity-cli profile."""
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    targets = _get_target_paths("agy", "foo", use_chezmoi=False)
    assert targets == [
        Path("/home/u/.gemini/antigravity-cli/skills/foo/SKILL.md"),
    ]


def test_get_target_path_agy_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Antigravity deploys skills under ~/.gemini/antigravity-cli/skills/."""
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    target = _get_target_path("agy", "foo", use_chezmoi=False)
    assert target == Path("/home/u/.gemini/antigravity-cli/skills/foo/SKILL.md")


def test_get_target_path_agy_chezmoi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Antigravity's nested subpath only dot-prefixes the first segment."""
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", Path("/c/home"))
    target = _get_target_path("agy", "foo", use_chezmoi=True)
    assert target == Path("/c/home/dot_gemini/antigravity-cli/skills/foo/SKILL.md")
