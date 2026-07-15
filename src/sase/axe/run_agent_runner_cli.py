"""CLI argument and prompt-file helpers for ``run_agent_runner``."""

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
from sase.axe.runner_args import parse_runner_bool_arg


@dataclass(frozen=True)
class _RunnerArgs:
    cl_name: str
    project_file: str
    workspace_dir: str
    output_path: str
    workspace_num: int
    workflow_name: str
    prompt_file: str
    timestamp: str
    update_target: str
    project_name: str
    is_home_mode: bool


def parse_runner_args(argv: Sequence[str]) -> _RunnerArgs:
    """Parse the runner's positional argv contract."""
    if len(argv) != 13:
        print(
            f"Usage: {argv[0]} <cl_name> <project_file> <workspace_dir> "
            "<output_path> <workspace_num> <workflow_name> <prompt_file> <timestamp> "
            "<update_target> <project_name> "
            "<cl_name_for_history> <is_home_mode>",
            file=sys.stderr,
        )
        sys.exit(1)

    return _RunnerArgs(
        cl_name=argv[1],
        project_file=argv[2],
        workspace_dir=argv[3],
        output_path=argv[4],
        workspace_num=int(argv[5]),
        workflow_name=argv[6],
        prompt_file=argv[7],
        timestamp=argv[8],
        update_target=argv[9],
        project_name=argv[10],
        # argv[11] (cl_name_for_history) is no longer used here; prompt
        # history is saved by the TUI before launch.
        is_home_mode=parse_runner_bool_arg(argv[12]),
    )


def read_prompt_file(
    prompt_file: str,
    *,
    refreshed_fallback_file: str | None = None,
) -> str:
    """Read and unlink the temporary submitted prompt file.

    A refreshed runner may recover from a missing one-shot prompt file by
    reading the persisted launch-boundary artifact. The artifact is never
    unlinked.
    """
    try:
        try:
            with open(prompt_file, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            if (
                RUNNER_CODE_REFRESHED_ENV not in os.environ
                or refreshed_fallback_file is None
            ):
                raise
            with open(refreshed_fallback_file, encoding="utf-8") as f:
                return f.read()
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass
