"""Advisory linked-repository coverage for the commit finalizer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    mark_opened_sibling,
    read_result_json,
    run_finalizer,
    set_agent_env,
    set_clean_main,
)


def test_env_none_strategy_dirty_sibling_triggers_advisory_follow_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    static_sibling = tmp_path / "home" / ".local" / "share" / "chezmoi"
    main.mkdir()
    init_git_repo(static_sibling)
    dirty_file = static_sibling / "dotfile"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "chezmoi",
                    "workspace_dir": str(static_sibling),
                    "workspace_strategy": "none",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        return InvokeResult(content="not mine")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nnot mine"
    assert "Advisory uncommitted changes detected" in prompts[0]
    assert "static linked repo chezmoi" in prompts[0]
    assert "dotfile" in prompts[0]
    assert f"cd {static_sibling.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]
    assert "will not make the finalizer fail" in prompts[0]
    assert dirty_file.exists()
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "advisory_dirty_remaining"
    assert result_json["changed_files"] == []
    assert result_json["advisory_changed_files"] == ["chezmoi:dotfile"]


def test_config_fallback_reports_none_strategy_absolute_sibling_as_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    chezmoi = tmp_path / "home" / ".local" / "share" / "chezmoi"
    primary.mkdir()
    workspace.mkdir()
    init_git_repo(chezmoi)
    dirty_file = chezmoi / "dotfile"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    project_file = tmp_path / "project.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: sase\n", encoding="utf-8")
    (primary / "sase.yml").write_text(
        "sibling_repos:\n"
        "  - name: chezmoi\n"
        f"    path: {chezmoi}\n"
        "    workspace:\n"
        "      strategy: none\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    set_agent_env(monkeypatch, workspace)
    set_clean_main(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(project_file))
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    artifacts_dir = tmp_path / "artifacts"
    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized static sibling")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert result.content == "primary response\n\nfinalized static sibling"
    assert provider.invoke.call_count == 1
    assert "static linked repo chezmoi" in prompts[0]
    assert "dotfile" in prompts[0]
    assert f"cd {chezmoi.resolve()}" in prompts[0]
    assert not dirty_file.exists()
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "advisory_clean_after_pass"
    assert result_json["changed_files"] == []
    assert result_json["advisory_changed_files"] == []


def test_config_fallback_checks_managed_root_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    sibling_primary = tmp_path / "sase-core"
    managed_root = tmp_path / "managed"
    managed_sibling = managed_root / "suite" / "sase-core_10"
    primary.mkdir()
    workspace.mkdir()
    sibling_primary.mkdir()
    init_git_repo(managed_sibling)
    dirty_file = managed_sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    project_file = tmp_path / "project.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: sase\n", encoding="utf-8")
    (primary / "sase.yml").write_text(
        "workspace:\n"
        f"  root: {managed_root}\n"
        "  project_key: suite\n"
        "sibling_repos:\n"
        "  - name: core\n"
        "    path: ../sase-core\n"
        "    description: Rust core checkout.\n",
        encoding="utf-8",
    )
    set_agent_env(monkeypatch, workspace)
    set_clean_main(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(project_file))
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", managed_sibling)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized core")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert result.content == "primary response\n\nfinalized core"
    assert provider.invoke.call_count == 1
    assert f"cd {managed_sibling.resolve()}" in prompts[0]
    assert "dirty.txt" in prompts[0]


def test_mixed_dirty_siblings_report_static_but_only_suffix_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    suffix_sibling = tmp_path / "sase-core_10"
    static_sibling = tmp_path / "home" / ".local" / "share" / "chezmoi"
    main.mkdir()
    init_git_repo(suffix_sibling)
    init_git_repo(static_sibling)
    suffix_file = suffix_sibling / "core.txt"
    static_file = static_sibling / "dotfile"
    suffix_file.write_text("dirty\n", encoding="utf-8")
    static_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "workspace_dir": str(suffix_sibling),
                    "workspace_strategy": "suffix",
                },
                {
                    "name": "chezmoi",
                    "workspace_dir": str(static_sibling),
                    "workspace_strategy": "none",
                },
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", suffix_sibling)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        suffix_file.unlink()
        return InvokeResult(content="finalized suffix sibling")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized suffix sibling"
    assert "linked repo core" in prompts[0]
    assert "core.txt" in prompts[0]
    assert "static linked repo chezmoi" in prompts[0]
    assert "dotfile" in prompts[0]
    assert f"cd {static_sibling.resolve()}" in prompts[0]
    assert static_file.exists()
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "advisory_dirty_remaining"
    assert result_json["changed_files"] == []
    assert result_json["advisory_changed_files"] == ["chezmoi:dotfile"]
