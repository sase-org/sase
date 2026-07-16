"""Tests for ``sase workspace`` project resolution."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.sibling_repos import opened_sibling_names
from tests.main.workspace_handler_helpers import make_args


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_project(home: Path, name: str, content: str) -> Path:
    project_dir = home / ".sase" / "projects" / name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(content, encoding="utf-8")
    return project_file


def _install_lifecycle_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    def read_lifecycle(content: str) -> SimpleNamespace:
        for line in content.splitlines():
            if line.startswith("NAME:"):
                break
            if line.startswith("PROJECT_STATE:"):
                state = line.split(":", 1)[1].strip()
                return SimpleNamespace(
                    state={"active": "enabled", "inactive": "disabled"}.get(
                        state, state
                    ),
                    explicit=True,
                )
        return SimpleNamespace(state="enabled", explicit=False)

    def apply_lifecycle(content: str, state: str) -> str:
        state = {"active": "enabled", "inactive": "disabled"}.get(state, state)
        lines = content.splitlines(keepends=True)
        line = f"PROJECT_STATE: {state}\n"
        for index, existing in enumerate(lines):
            if existing.startswith("PROJECT_STATE:"):
                lines[index] = line
                return "".join(lines)
        insert_index = len(lines)
        for index, existing in enumerate(lines):
            if existing.startswith(("RUNNING:", "NAME:")):
                insert_index = index
                break
        if insert_index == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.insert(insert_index, line)
        return "".join(lines)

    monkeypatch.setattr(
        "sase.main.workspace_handler.read_project_lifecycle_from_content",
        read_lifecycle,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler.apply_project_lifecycle_update",
        apply_lifecycle,
    )


def _setup_current_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sibling_name: str = "core",
) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    main = tmp_path / "main"
    sibling = tmp_path / sibling_name
    _git_init(main)
    _git_init(sibling)
    _write_project(home, "main", f"WORKSPACE_DIR: {main}\nNAME: main\n")
    monkeypatch.chdir(main)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda cwd=None: "main",
    )

    config = {
        "workspace": {"root": str(tmp_path / "managed")},
        "sibling_repos": [
            {
                "name": sibling_name,
                "path": f"../{sibling_name}",
                "description": "sibling",
            }
        ],
    }
    monkeypatch.setattr(
        "sase.main.workspace_handler.load_merged_config", lambda: config
    )
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: config)
    _install_lifecycle_stubs(monkeypatch)
    return home, main, sibling


class TestWorkspaceProjectResolution:
    def test_missing_project_inference_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Empty home with no projects directory and stub the inference
        # to ensure we don't accidentally pick up the dev's real projects.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sase.bead.project_name.infer_project_name_from_cwd",
            lambda cwd=None: None,
        )
        args = make_args(workspace_subcommand="list", project=None, json=False)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "infer project" in capsys.readouterr().err

    def test_open_materializes_configured_sibling_project_spec(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        home, _, sibling = _setup_current_project(tmp_path, monkeypatch)
        checkout = str(tmp_path / "managed" / "core_10")
        args = make_args(
            workspace_subcommand="open",
            project="core",
            reason="prepare workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        with (
            pytest.MonkeyPatch.context() as mp,
            pytest.raises(SystemExit) as exc,
        ):
            mp.setattr(
                "sase.sdd.files.ensure_bare_git_sdd_initialized",
                lambda *_args, **_kwargs: None,
            )
            mp.setattr(
                "sase.main.workspace_handler._resolve_checkout_path",
                lambda *_args, **_kwargs: checkout,
            )
            mp.setattr(
                "sase.axe.runner_workspace.prepare_workspace",
                lambda *_args, **_kwargs: True,
            )
            handle_workspace_command(args)

        assert exc.value.code == 0
        project_file = home / ".sase" / "projects" / "core" / "core.sase"
        content = project_file.read_text(encoding="utf-8")
        assert "PROJECT_STATE: sibling\n" in content
        assert f"WORKSPACE_DIR: {sibling}\n" in content
        assert capsys.readouterr().out.strip() == checkout

    def test_env_linked_repo_materializes_when_current_project_is_unknown(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("SASE_HOME", raising=False)
        main = tmp_path / "main"
        core = tmp_path / "core"
        _git_init(main)
        _git_init(core)
        monkeypatch.chdir(main)
        monkeypatch.setenv(
            "SASE_LINKED_REPOS_JSON",
            json.dumps(
                [
                    {
                        "name": "core",
                        "primary_dir": str(core),
                        "workspace_strategy": "suffix",
                    }
                ]
            ),
        )
        monkeypatch.setattr(
            "sase.bead.project_name.infer_project_name_from_cwd",
            lambda cwd=None: None,
        )
        config = {"workspace": {"root": str(tmp_path / "managed")}}
        monkeypatch.setattr(
            "sase.main.workspace_handler.load_merged_config", lambda: config
        )
        monkeypatch.setattr("sase.config.core.load_merged_config", lambda: config)
        _install_lifecycle_stubs(monkeypatch)
        args = make_args(workspace_subcommand="list", project="core", json=True)

        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        project_file = home / ".sase" / "projects" / "core" / "core.sase"
        content = project_file.read_text(encoding="utf-8")
        assert "PROJECT_STATE: sibling\n" in content
        assert f"WORKSPACE_DIR: {core}\n" in content
        payload = json.loads(capsys.readouterr().out)
        assert payload["project"] == "core"

    def test_implicit_state_linked_repo_spec_is_healed_to_sibling(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        home, _, sibling = _setup_current_project(tmp_path, monkeypatch)
        project_file = _write_project(
            home,
            "core",
            f"WORKSPACE_DIR: {sibling}\nNAME: core\n",
        )
        args = make_args(workspace_subcommand="list", project="core", json=True)

        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: sibling\n" in project_file.read_text(encoding="utf-8")

    def test_open_existing_sibling_project_spec_records_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        home, _, sibling = _setup_current_project(tmp_path, monkeypatch)
        _write_project(
            home,
            "core",
            f"PROJECT_STATE: sibling\nWORKSPACE_DIR: {sibling}\nNAME: core\n",
        )
        artifacts_dir = tmp_path / "artifacts"
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
        checkout = str(tmp_path / "managed" / "core_10")
        args = make_args(
            workspace_subcommand="open",
            project="core",
            reason="prepare workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        with (
            pytest.MonkeyPatch.context() as mp,
            pytest.raises(SystemExit) as exc,
        ):
            mp.setattr(
                "sase.sdd.files.ensure_bare_git_sdd_initialized",
                lambda *_args, **_kwargs: None,
            )
            mp.setattr(
                "sase.main.workspace_handler._resolve_checkout_path",
                lambda *_args, **_kwargs: checkout,
            )
            mp.setattr(
                "sase.axe.runner_workspace.prepare_workspace",
                lambda *_args, **_kwargs: True,
            )
            handle_workspace_command(args)

        assert exc.value.code == 0
        assert capsys.readouterr().out.strip() == checkout
        assert opened_sibling_names(artifacts_dir) == {"core"}

    def test_unconfigured_unknown_project_still_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _setup_current_project(tmp_path, monkeypatch, sibling_name="core-extra")
        args = make_args(workspace_subcommand="list", project="core", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 2
        assert "Project 'core' has no WORKSPACE_DIR" in capsys.readouterr().err

    def test_configured_sibling_with_explicit_non_sibling_state_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        home, _, _ = _setup_current_project(tmp_path, monkeypatch)
        _write_project(home, "core", "PROJECT_STATE: active\nNAME: core\n")
        args = make_args(workspace_subcommand="list", project="core", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 2
        assert "explicit PROJECT_STATE 'enabled'" in capsys.readouterr().err

    def test_configured_sibling_with_workspace_dir_and_explicit_enabled_state_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        home, _, sibling = _setup_current_project(tmp_path, monkeypatch)
        _write_project(
            home,
            "core",
            f"PROJECT_STATE: active\nWORKSPACE_DIR: {sibling}\nNAME: core\n",
        )
        args = make_args(workspace_subcommand="list", project="core", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 2
        assert "explicit PROJECT_STATE 'enabled'" in capsys.readouterr().err
