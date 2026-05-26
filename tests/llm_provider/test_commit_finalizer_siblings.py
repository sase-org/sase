"""Configured sibling repository coverage for the shared commit finalizer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def _init_bare_remote(path: Path) -> Path:
    subprocess.run(["git", "init", "--bare", "-q", str(path)], check=True)
    return path


def _add_origin(repo: Path, remote: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True
    )


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


def _write_tool_call_record(artifacts_dir: Path, record: dict[str, object]) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with open(artifacts_dir / "tool_calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _write_run_started_at(artifacts_dir: Path, started_at: datetime) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"run_started_at": started_at.isoformat()}),
        encoding="utf-8",
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


def test_dirty_observed_same_repo_workspace_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    observed = tmp_path / "sase_11"
    remote = _init_bare_remote(tmp_path / "origin.git")
    _init_git_repo(main)
    _init_git_repo(observed)
    _add_origin(main, remote)
    _add_origin(observed, remote)
    artifacts_dir = tmp_path / "artifacts"
    _write_run_started_at(
        artifacts_dir,
        datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    dirty_file = observed / "sdd" / "epics" / "observed.png"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("dirty\n", encoding="utf-8")
    _write_tool_call_record(
        artifacts_dir,
        {
            "cwd": str(observed),
            "tool_input_summary": {
                "command": f"python render.py {dirty_file.resolve()}"
            },
            "tool_response_summary": {},
        },
    )
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
    provider = MagicMock()
    prompts: list[str] = []

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized observed workspace")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized observed workspace"
    assert "observed workspace" in prompts[0]
    assert "sdd/epics/observed.png" in prompts[0]
    assert f"cd {observed.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]


def test_old_observed_same_repo_workspace_dirty_file_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    observed = tmp_path / "sase_11"
    remote = _init_bare_remote(tmp_path / "origin.git")
    _init_git_repo(main)
    _init_git_repo(observed)
    _add_origin(main, remote)
    _add_origin(observed, remote)
    dirty_file = observed / "old.txt"
    dirty_file.write_text("old\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    _write_run_started_at(
        artifacts_dir,
        datetime.fromtimestamp(dirty_file.stat().st_mtime, tz=UTC) + timedelta(hours=1),
    )
    _write_tool_call_record(
        artifacts_dir,
        {
            "cwd": str(observed),
            "tool_input_summary": {"command": f"git -C {observed.resolve()} status"},
            "tool_response_summary": {},
        },
    )
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
    provider = MagicMock()

    result = _run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert dirty_file.exists()
    assert '"status": "clean"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_observed_workspace_with_different_remote_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    other = tmp_path / "other_10"
    _init_git_repo(main)
    _init_git_repo(other)
    _add_origin(main, _init_bare_remote(tmp_path / "origin-main.git"))
    _add_origin(other, _init_bare_remote(tmp_path / "origin-other.git"))
    dirty_file = other / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    _write_run_started_at(
        artifacts_dir,
        datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    _write_tool_call_record(
        artifacts_dir,
        {
            "cwd": str(other),
            "tool_input_summary": {"file_path": str(dirty_file.resolve())},
            "tool_response_summary": {},
        },
    )
    _set_agent_env(monkeypatch, main)
    _set_clean_main(monkeypatch)
    provider = MagicMock()

    result = _run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert dirty_file.exists()


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
