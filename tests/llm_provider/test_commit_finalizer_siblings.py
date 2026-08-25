"""Linked-repo dirty discovery for the built-in commit finalizer.

The finalizer is canonical on ``linked_repos`` terminology and env/markers but
still honors the deprecated ``sibling`` env vars and opened-sibling markers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    add_origin,
    collected_dirty_state,
    init_bare_remote,
    init_git_repo,
    mark_opened_sibling,
    set_agent_env,
    set_clean_main,
    write_tool_call_record,
)


def _sibling_names(state) -> set[str]:
    return {repo.name for repo in state.repos if repo.kind == "sibling"}


def test_dirty_configured_sibling_without_open_marker_is_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    (sibling / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = collected_dirty_state(main, artifacts_dir)

    assert _sibling_names(state) == {"core"}
    assert any("dirty.txt" in repo.changed_files for repo in state.repos)


def test_dirty_configured_sibling_with_open_marker_is_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", sibling)
    (sibling / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    state = collected_dirty_state(main, artifacts_dir)

    assert _sibling_names(state) == {"core"}


def test_opened_dirty_sibling_uses_recorded_path_when_config_omits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(SIBLING_REPOS_JSON_ENV, json.dumps([]))
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", sibling)
    (sibling / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    state = collected_dirty_state(main, artifacts_dir)

    assert _sibling_names(state) == {"core"}
    assert any(repo.path == str(sibling.resolve()) for repo in state.repos)


def test_dirty_observed_same_repo_workspace_from_artifacts_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    observed = tmp_path / "sase_12"
    remote = init_bare_remote(tmp_path / "origin.git")
    init_git_repo(main)
    init_git_repo(observed)
    add_origin(main, remote)
    add_origin(observed, remote)
    artifacts_dir = tmp_path / "artifacts"
    dirty_file = observed / "sdd" / "plans" / "observed.png"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("dirty\n", encoding="utf-8")
    write_tool_call_record(
        artifacts_dir,
        {
            "cwd": str(observed),
            "tool_input_summary": {
                "command": f"python render.py {dirty_file.resolve()}"
            },
            "tool_response_summary": {},
        },
    )
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)

    state = collected_dirty_state(main, artifacts_dir)

    assert state.is_clean


def test_dirty_primary_sibling_checkout_is_ignored_when_workspace_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    primary_sibling = tmp_path / "sase-core"
    workspace_sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(primary_sibling)
    init_git_repo(workspace_sibling)
    (primary_sibling / "dirty-primary.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(primary_sibling),
                    "workspace_dir": str(workspace_sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", workspace_sibling)

    state = collected_dirty_state(main, artifacts_dir)

    assert state.is_clean


def test_multiple_dirty_configured_siblings_are_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    alpha = tmp_path / "sase-alpha_10"
    beta = tmp_path / "sase-beta_10"
    main.mkdir()
    init_git_repo(alpha)
    init_git_repo(beta)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {"name": "alpha", "workspace_dir": str(alpha)},
                {"name": "beta", "workspace_dir": str(beta)},
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "alpha", alpha)
    mark_opened_sibling(monkeypatch, artifacts_dir, "beta", beta)
    (alpha / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (beta / "beta.txt").write_text("beta\n", encoding="utf-8")

    state = collected_dirty_state(main, artifacts_dir)

    assert _sibling_names(state) == {"alpha", "beta"}


def test_dirty_configured_suffix_siblings_are_discovered_without_open_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    alpha = tmp_path / "sase-alpha_10"
    beta = tmp_path / "sase-beta_10"
    main.mkdir()
    init_git_repo(alpha)
    init_git_repo(beta)
    (beta / "beta.txt").write_text("beta\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {"name": "alpha", "workspace_dir": str(alpha)},
                {"name": "beta", "workspace_dir": str(beta)},
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    mark_opened_sibling(monkeypatch, artifacts_dir, "alpha", alpha)
    (alpha / "alpha.txt").write_text("alpha\n", encoding="utf-8")

    state = collected_dirty_state(main, artifacts_dir)

    assert _sibling_names(state) == {"alpha", "beta"}
