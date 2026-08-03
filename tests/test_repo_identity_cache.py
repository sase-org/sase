"""Regression coverage for process-lifetime repository identity caches."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase._linked_repo_config import resolution_config
from sase._linked_repo_identity import (
    full_github_repo_name,
    reset_repo_identity_caches,
)


def test_reset_repo_identity_caches_reprobes_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    remotes = [
        "git@github.com:acme/widget.git",
        "git@github.com:other/widget.git",
    ]
    calls = 0

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        remote = remotes[min(calls, len(remotes) - 1)]
        calls += 1
        return subprocess.CompletedProcess([], 0, stdout=f"{remote}\n", stderr="")

    monkeypatch.setattr("sase._linked_repo_identity.subprocess.run", run)

    assert full_github_repo_name(primary, "widget--plans", config={}) == (
        "acme/widget--plans"
    )
    assert full_github_repo_name(primary, "widget--plans", config={}) == (
        "acme/widget--plans"
    )
    assert calls == 1

    reset_repo_identity_caches()

    assert full_github_repo_name(primary, "widget--plans", config={}) == (
        "other/widget--plans"
    )
    assert calls == 2


def test_resolution_config_caches_only_implicit_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def load() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"generation": calls}

    monkeypatch.setattr("sase.config.core.load_merged_config", load)
    monkeypatch.setattr(
        "sase._linked_repo_config.read_project_local_config",
        lambda _primary: {},
    )

    first = resolution_config(str(tmp_path), None)
    second = resolution_config(str(tmp_path), None)
    explicit = {"generation": "explicit"}

    assert first is second
    assert calls == 1
    assert resolution_config(str(tmp_path), explicit) is explicit

    reset_repo_identity_caches()

    assert resolution_config(str(tmp_path), None) == {"generation": 2}
    assert calls == 2
