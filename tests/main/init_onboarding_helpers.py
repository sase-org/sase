"""Shared helpers for bare ``sase init`` onboarding tests."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_project_scope import InitProjectTarget
from sase.main.init_registry import InitCommandScope, InitCommandSpec


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
    scope: InitCommandScope = "project",
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
        scope=scope,
    )


def _reject_prompt(prompt: str) -> str:
    raise AssertionError(f"unexpected prompt: {prompt}")


def _batch_target(
    tmp_path: Path,
    name: str,
    *,
    display_name: str | None = None,
    unavailable: str | None = None,
    warnings: tuple[str, ...] = (),
) -> InitProjectTarget:
    workspace = tmp_path / name
    workspace.mkdir()
    project_file = tmp_path / f"{name}.sase"
    project_file.write_text("NAME: test\n", encoding="utf-8")
    return InitProjectTarget(
        project_name=name,
        display_name=display_name or name,
        project_file=project_file,
        workspace_dir=workspace,
        warnings=warnings,
        unavailable_reason=unavailable,
    )
