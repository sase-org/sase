"""Shared helpers for ``sase memory init`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command, plan_init_memory
from sase.main.init_plan import InitPlan


SASE_MEMORY_HEADER = "# SASE = Structured Agentic Software Engineering"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def prettier_command() -> list[str]:
    prettier = shutil.which("prettier")
    if prettier is not None:
        return [prettier]
    local_prettier = _REPO_ROOT / "node_modules" / ".bin" / "prettier"
    if local_prettier.exists():
        return [str(local_prettier)]
    pytest.skip("prettier not installed")


def single_line(text: str) -> str:
    return " ".join(text.split())


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


def long_note(
    body: str,
    *,
    description: str | None = "Long description.",
    extra_frontmatter: str = "",
) -> str:
    lines = ["---", "type: long", "parent: AGENTS.md"]
    if description is not None:
        lines.append(f"description: {description}")
    if extra_frontmatter:
        lines.extend(extra_frontmatter.strip().splitlines())
    lines.extend(["---", body])
    return "\n".join(lines)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_handler(
    *, no_commit: bool = True, check: bool = False, message: str | None = None
) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(
            argparse.Namespace(no_commit=no_commit, check=check, message=message)
        )
    return int(exc.value.code)


def run_memory(
    *, no_commit: bool = True, check: bool = False, message: str | None = None
) -> int:
    return init_memory_handler.run_init_memory(
        argparse.Namespace(no_commit=no_commit, check=check, message=message)
    )


def plan_memory(*, no_commit: bool = True) -> InitPlan:
    return plan_init_memory(argparse.Namespace(no_commit=no_commit))


def patch_standard_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    home_root: Path,
    config_dir: Path,
    use_chezmoi: bool = False,
    project_is_vcs: bool = True,
) -> None:
    if project_is_vcs:
        git_marker = project_root / ".git"
        if not git_marker.exists():
            git_marker.mkdir()
        config_path = project_root / "sase.yml"
        if not config_path.exists():
            write(config_path, "memory:\n  enabled: true\n")
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: use_chezmoi)
