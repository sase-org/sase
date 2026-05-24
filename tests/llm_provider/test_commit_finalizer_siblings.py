"""Configured sibling repository coverage for the shared commit finalizer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _set_agent_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260521_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)


def _set_clean_main(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    build = MagicMock(return_value=(False, [], "", ""))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details", build
    )
    return build


def _run_finalizer(provider: MagicMock, artifacts_dir: Path) -> InvokeResult:
    return run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )


def test_dirty_configured_sibling_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    _init_git_repo(sibling)
    dirty_file = sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
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

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized sibling")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized sibling"
    assert "sibling repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {sibling.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]


def test_dirty_primary_sibling_checkout_is_ignored_when_workspace_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    primary_sibling = tmp_path / "sase-core"
    workspace_sibling = tmp_path / "sase-core_10"
    main.mkdir()
    _init_git_repo(primary_sibling)
    _init_git_repo(workspace_sibling)
    (primary_sibling / "dirty-primary.txt").write_text("dirty\n", encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
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
    provider = MagicMock()

    result = _run_finalizer(provider, tmp_path / "artifacts")

    provider.invoke.assert_not_called()
    assert result.content == "primary response"


def test_env_none_strategy_dirty_sibling_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    static_sibling = tmp_path / "home" / ".local" / "share" / "chezmoi"
    main.mkdir()
    _init_git_repo(static_sibling)
    dirty_file = static_sibling / "dotfile"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
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
    provider = MagicMock()

    result = _run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert dirty_file.exists()
    assert '"status": "clean"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_config_fallback_ignores_none_strategy_absolute_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    chezmoi = tmp_path / "home" / ".local" / "share" / "chezmoi"
    primary.mkdir()
    workspace.mkdir()
    _init_git_repo(chezmoi)
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
    _set_agent_env(monkeypatch, workspace)
    _set_clean_main(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(project_file))
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    artifacts_dir = tmp_path / "artifacts"
    provider = MagicMock()

    result = _run_finalizer(provider, artifacts_dir)

    assert result.content == "primary response"
    provider.invoke.assert_not_called()
    assert dirty_file.exists()
    assert '"status": "clean"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


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
    _init_git_repo(managed_sibling)
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
    _set_agent_env(monkeypatch, workspace)
    _set_clean_main(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(project_file))
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized core")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, tmp_path / "artifacts")

    assert result.content == "primary response\n\nfinalized core"
    assert provider.invoke.call_count == 1
    assert f"cd {managed_sibling.resolve()}" in prompts[0]
    assert "dirty.txt" in prompts[0]


def test_multiple_dirty_configured_siblings_are_listed_and_rechecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    alpha = tmp_path / "sase-alpha_10"
    beta = tmp_path / "sase-beta_10"
    main.mkdir()
    _init_git_repo(alpha)
    _init_git_repo(beta)
    alpha_file = alpha / "alpha.txt"
    beta_file = beta / "beta.txt"
    alpha_file.write_text("alpha\n", encoding="utf-8")
    beta_file.write_text("beta\n", encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {"name": "alpha", "workspace_dir": str(alpha)},
                {"name": "beta", "workspace_dir": str(beta)},
            ]
        ),
    )

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        alpha_file.unlink()
        beta_file.unlink()
        return InvokeResult(content="finalized siblings")

    provider.invoke.side_effect = invoke

    _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert "sibling repo alpha" in prompts[0]
    assert "alpha.txt" in prompts[0]
    assert "sibling repo beta" in prompts[0]
    assert "beta.txt" in prompts[0]
    assert '"status": "finalized"' in (
        tmp_path / "artifacts" / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_mixed_dirty_siblings_ignore_static_and_recheck_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    suffix_sibling = tmp_path / "sase-core_10"
    static_sibling = tmp_path / "home" / ".local" / "share" / "chezmoi"
    main.mkdir()
    _init_git_repo(suffix_sibling)
    _init_git_repo(static_sibling)
    suffix_file = suffix_sibling / "core.txt"
    static_file = static_sibling / "dotfile"
    suffix_file.write_text("dirty\n", encoding="utf-8")
    static_file.write_text("dirty\n", encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
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

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        suffix_file.unlink()
        return InvokeResult(content="finalized suffix sibling")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized suffix sibling"
    assert "sibling repo core" in prompts[0]
    assert "core.txt" in prompts[0]
    assert "sibling repo chezmoi" not in prompts[0]
    assert "dotfile" not in prompts[0]
    assert f"cd {static_sibling.resolve()}" not in prompts[0]
    assert static_file.exists()
    assert '"status": "finalized"' in (
        tmp_path / "artifacts" / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")
