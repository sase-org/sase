"""Memory-backed flow tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import sase.config.core as config_core
from sase.main.init_memory_handler import plan_init_memory, run_init_memory
from sase.main import init_memory_handler
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec, iter_init_command_specs
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_memory,
    write,
)
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _plan,
    _reject_prompt,
    _spec,
)


def test_bare_init_routes_confirmation_and_fold_subject_through_injected_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    (project_root / "sase.yml").unlink()
    write(project_root / "AGENTS.md", "# Project Instructions\n")
    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(init_memory_handler, "run_before_commit_hook", lambda cwd: True)

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=b" M AGENTS.md\0", stderr=b"")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "commit" in cmd:
            return MagicMock(
                returncode=0, stdout="[main abc1234] committed\n", stderr=""
            )
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)
    prompts: list[str] = []
    responses = iter(("yes", "sync project instructions"))

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    specs = tuple(spec for spec in iter_init_command_specs() if spec.name == "memory")
    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=answer,
    )

    assert exit_code == 0
    assert prompts[0].startswith("Run `sase init memory` now?")
    assert prompts[1] == "Commit message > "
    commit = next(cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd)
    assert commit[commit.index("-m") + 1] == (
        "docs(memory): sync project instructions\n\nSASE_TYPE=memory"
    )


def test_bare_init_check_reports_nested_agent_doc_provider_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(nested / "AGENTS.md", "# Tape Instructions\n\nUse vhs for tapes.\n")
    capsys.readouterr()
    calls: list[str] = []
    specs = (
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=plan_init_memory,
            run=run_init_memory,
        ),
        _spec("sdd", _plan("sdd", summary="sdd current"), calls),
        _spec("skills", _plan("skills", summary="skills current"), calls),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Needs attention:" in out
    assert "init memory" in out
    assert "provider shims" in out
    assert "No init subcommands need to run" not in out
    assert calls == []


def test_bare_init_does_not_create_unmanaged_project_memory_or_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    (project_root / "sase.yml").unlink()
    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: False)
    specs = tuple(spec for spec in iter_init_command_specs() if spec.name == "memory")
    args = argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=True,
        check=False,
        no_commit=True,
    )

    assert (
        run_init_onboarding(
            args,
            specs=specs,
            stdin=StringIO(),
            input_func=_reject_prompt,
        )
        == 0
    )

    assert not (project_root / "sase" / "memory").exists()
    assert not (project_root / "memory").exists()
    assert not (project_root / "AGENTS.md").exists()
    assert (home_root / "sase" / "memory" / "sase.md").exists()
    assert (home_root / "AGENTS.md").exists()


def test_bare_init_yes_repairs_unreferenced_long_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: False)
    # Explicitly enabled memory with no title uses the derived project title.
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nsdd:\n  version_controlled: true\n",
    )
    write(project_root / "AGENTS.md", "# Agent Instructions\n\n@memory/sase.md\n")
    write(
        project_root / "memory" / "cli_rules.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    specs = tuple(spec for spec in iter_init_command_specs() if spec.name == "memory")
    args = argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=True,
        check=False,
        no_commit=True,
    )

    exit_code = run_init_onboarding(
        args,
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "## 2. Tier 2 (reference) Memory" in agents
    assert "### 2.1 `sase/memory/cli_rules.md`" in agents
    assert (project_root / "sase" / "memory" / "sase.md").exists()
    assert not (project_root / "memory").exists()
