"""Shared helpers for ``sase memory init`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command, plan_init_memory
from sase.main.init_plan import InitPlan


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_handler(*, no_commit: bool = True) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(argparse.Namespace(no_commit=no_commit))
    return int(exc.value.code)


def run_memory(*, no_commit: bool = True) -> int:
    return init_memory_handler.run_init_memory(argparse.Namespace(no_commit=no_commit))


def plan_memory(*, no_commit: bool = True) -> InitPlan:
    return plan_init_memory(argparse.Namespace(no_commit=no_commit))


def patch_standard_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    home_root: Path,
    config_dir: Path,
    use_chezmoi: bool = False,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: use_chezmoi)
