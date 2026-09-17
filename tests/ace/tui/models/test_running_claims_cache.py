"""Tests for cached RUNNING-claim parsing with uncached liveness."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models._loaders import _running_loaders as running_loaders
from sase.running_field import WorkspaceClaim


@pytest.fixture(autouse=True)
def _clear_running_claims_cache() -> None:
    running_loaders._RUNNING_CLAIMS_CACHE.clear()


def test_running_claims_cache_rechecks_pid_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_file = tmp_path / "project.sase"
    project_file.write_text("RUNNING:\n", encoding="utf-8")
    claim = WorkspaceClaim(1, "crs", "feat", 123, "20260917120000")
    parse_calls = 0
    pid_checks = 0

    def get_claims(_project_file: str) -> list[WorkspaceClaim]:
        nonlocal parse_calls
        parse_calls += 1
        return [claim]

    def is_live(pid: int | None) -> bool:
        nonlocal pid_checks
        pid_checks += 1
        return pid == 123

    monkeypatch.setattr(running_loaders, "get_claimed_workspaces", get_claims)
    monkeypatch.setattr(running_loaders, "is_process_running", is_live)

    first = running_loaders.resolve_running_field_claims([str(project_file)])
    second = running_loaders.resolve_running_field_claims([str(project_file)])

    assert len(first) == 1
    assert len(second) == 1
    assert parse_calls == 1
    assert pid_checks == 2


def test_stale_claim_cleanup_invalidates_running_claims_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_file = tmp_path / "project.sase"
    project_file.write_text("RUNNING:\n", encoding="utf-8")
    claim = WorkspaceClaim(1, "crs", "feat", 123, "20260917120000")
    parse_calls = 0
    releases = 0

    def get_claims(_project_file: str) -> list[WorkspaceClaim]:
        nonlocal parse_calls
        parse_calls += 1
        return [claim]

    def release(
        _project_file: str,
        _workspace_num: int,
        _workflow: str,
        _cl_name: str | None,
        *,
        caller_tag: str,
    ) -> None:
        nonlocal releases
        del caller_tag
        releases += 1

    monkeypatch.setattr(running_loaders, "get_claimed_workspaces", get_claims)
    monkeypatch.setattr(running_loaders, "is_process_running", lambda _pid: False)
    monkeypatch.setattr(
        running_loaders,
        "_stale_claim_is_releasable",
        lambda _project_file, _claim: True,
    )
    monkeypatch.setattr(running_loaders, "release_workspace", release)

    assert running_loaders.resolve_running_field_claims([str(project_file)]) == []
    assert running_loaders.resolve_running_field_claims([str(project_file)]) == []

    assert parse_calls == 2
    assert releases == 2
