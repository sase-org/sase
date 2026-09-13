from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _configure_git_commit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git commits working when the suite redirects HOME away from ~/.gitconfig."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "SASE Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "sase-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "SASE Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "sase-test@example.com")

    config_count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    monkeypatch.setenv(f"GIT_CONFIG_KEY_{config_count}", "commit.gpgsign")
    monkeypatch.setenv(f"GIT_CONFIG_VALUE_{config_count}", "false")
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(config_count + 1))
