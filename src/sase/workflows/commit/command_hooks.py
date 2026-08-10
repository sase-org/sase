"""Configurable commands that run before and after commit dispatch."""

from __future__ import annotations

import subprocess
import sys
from typing import Literal

from sase.config.core import load_merged_config
from sase.output import print_status
from sase.workflows.commit.hook_utils import get_repo_root

CommitHookPhase = Literal["before", "after"]


def _run_commit_hook(phase: CommitHookPhase, cwd: str) -> bool:
    """Run the configured hook for *phase* in the repository root."""
    config = load_merged_config()
    hooks = config.get("commit_hooks", {})
    cmd = hooks.get(phase, "") if isinstance(hooks, dict) else ""
    if not cmd:
        return True
    repo_root = get_repo_root(cwd) or cwd
    print_status(f"Running {phase} commit hook: {cmd}", "progress")
    result = subprocess.run(
        cmd, shell=True, cwd=repo_root, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print_status(
            f"{phase.capitalize()} commit hook failed "
            f"(exit {result.returncode}): {cmd}",
            "error",
        )
        tail = _commit_hook_output_tail(result.stdout, result.stderr)
        if tail:
            print(f"---- {phase} commit hook output tail ----", file=sys.stderr)
            print(tail, file=sys.stderr)
            print(f"---- end {phase} commit hook output ----", file=sys.stderr)
        return False
    return True


def run_before_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.before`` in the repository root."""
    return _run_commit_hook("before", cwd)


def run_after_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.after`` in the repository root."""
    return _run_commit_hook("after", cwd)


def _commit_hook_output_tail(stdout: str, stderr: str, *, max_lines: int = 50) -> str:
    """Return the last useful lines from captured commit-hook output."""
    lines: list[str] = []
    for label, text in (("stdout", stdout), ("stderr", stderr)):
        if not text:
            continue
        section = text.rstrip().splitlines()
        if not section:
            continue
        lines.append(f"[{label}]")
        lines.extend(section)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])
