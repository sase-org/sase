"""Shared helpers for ``sase memory init`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command, plan_init_memory
from sase.main.init_plan import InitPlan
from sase.markdown_width import prettier_markdown_argv


SASE_MEMORY_HEADER = "# SASE = Structured Agentic Software Engineering"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def prettier_command() -> list[str]:
    """Return an argv prefix invoking prettier with the shared Markdown flags.

    Callers must not append their own width or prose-wrap flags: deriving them
    from ``prettier_markdown_argv()`` is what keeps these checks honest when
    the declared width changes.
    """
    flags = prettier_markdown_argv()[1:]
    prettier = shutil.which("prettier")
    if prettier is not None:
        return [prettier, *flags]
    local_prettier = _REPO_ROOT / "node_modules" / ".bin" / "prettier"
    if local_prettier.exists():
        return [str(local_prettier), *flags]
    pytest.skip("prettier not installed")


def single_line(text: str) -> str:
    return " ".join(text.split())


def short_note(body: str) -> str:
    return "---\ntype: core\nparent: AGENTS.md\n---\n" + body


def long_note(
    body: str,
    *,
    description: str | None = "Long description.",
    extra_frontmatter: str = "",
) -> str:
    lines = ["---", "type: reference", "parent: AGENTS.md"]
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
    *,
    no_commit: bool = True,
    check: bool = False,
    message: str | None = None,
    enable_project_memory: bool = False,
) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(
            argparse.Namespace(
                no_commit=no_commit,
                check=check,
                message=message,
                enable_project_memory=enable_project_memory,
            )
        )
    return int(exc.value.code)


def run_memory(
    *,
    no_commit: bool = True,
    check: bool = False,
    message: str | None = None,
    enable_project_memory: bool = False,
) -> int:
    return init_memory_handler.run_init_memory(
        argparse.Namespace(
            no_commit=no_commit,
            check=check,
            message=message,
            enable_project_memory=enable_project_memory,
        )
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
            write(config_path, "is_sase_managed: true\n")
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: use_chezmoi)
