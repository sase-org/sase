"""Launch-time context detection for artifact-reference resolution."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path


def build_launch_artifact_ref_context[ContextT](
    *,
    artifact_ref_context_fn: Callable[..., ContextT],
    is_home_mode: bool,
    workspace_project_ref_fn: Callable[[Path], str | None],
) -> ContextT:
    """Build artifact context from the current managed-workspace environment.

    Uses ``cwd`` to locate the workspace, which is correct for the CLI and
    ACE callers that keep using this function. The prompt path must not call
    this: it resolves an explicit ``PromptRefContext`` per segment instead,
    via ``sase.artifact_ref_prompt_context``, derived from the prompt's own
    ``#git``/``#gh`` workflow tag or the launcher's recorded identity.
    """

    workspace = Path.cwd()
    workspace_num = _workspace_num_from_environment()
    project = workspace_project_ref_fn(workspace)
    if workspace_num is None:
        try:
            from sase.main.utils import ensure_project_file_and_get_workspace_num

            _project_file, detected_num, detected_project = (
                ensure_project_file_and_get_workspace_num(create_missing=False)
            )
            workspace_num = detected_num
            project = detected_project or project
        except Exception:
            pass
    if workspace_num is None:
        workspace_num = 0 if is_home_mode else 1
    return artifact_ref_context_fn(workspace, workspace_num, project=project)


def _workspace_num_from_environment() -> int | None:
    for name in (
        "SASE_AGENT_WORKSPACE_NUM",
        "SASE_GIT_WORKSPACE_NUM",
        "SASE_GH_WORKSPACE_NUM",
    ):
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


__all__ = ["build_launch_artifact_ref_context"]
