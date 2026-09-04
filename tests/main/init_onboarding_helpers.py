"""Shared helpers for bare ``sase init`` onboarding tests."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _args(
    *,
    yes: bool = False,
    check: bool = False,
    diff: bool = False,
    enable_project_memory: bool = False,
    all_projects: bool = False,
    json: bool = False,
    project: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=yes,
        check=check,
        diff=diff,
        enable_project_memory=enable_project_memory,
        all=all_projects,
        json=json,
        project=project,
    )


def _plan(
    command: str,
    *,
    actions: tuple[InitAction, ...] = (),
    summary: str = "",
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
    requires_tty: bool = False,
) -> InitPlan:
    return InitPlan(
        command=command,
        label=f"Init {command}",
        summary=summary,
        actions=actions,
        warnings=warnings,
        blockers=blockers,
        requires_tty=requires_tty,
    )


def _changed_action(path: str = "memory/sase.md") -> InitAction:
    return InitAction(Path(path), "update", "changed")


def _spec(
    name: str,
    plan: InitPlan,
    calls: list[str],
    args_seen: list[argparse.Namespace] | None = None,
    exit_code: int = 0,
) -> InitCommandSpec:
    def _run(args: argparse.Namespace) -> int:
        calls.append(name)
        if args_seen is not None:
            args_seen.append(args)
        return exit_code

    return InitCommandSpec(
        name=name,
        label=plan.label,
        plan=lambda args: plan,
        run=_run,
    )


def _reject_prompt(prompt: str) -> str:
    raise AssertionError(f"unexpected prompt: {prompt}")
