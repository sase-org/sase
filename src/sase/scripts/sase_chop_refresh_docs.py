#!/usr/bin/env python3
"""Builtin documentation-refresh proposal chop."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


DEFAULT_UPDATE_PROMPT = """\
Refresh the documentation for {project}.

Review the current repository behavior and the changes since the last documentation
refresh. Update user-facing documentation so it is accurate, complete, and clear to
someone new to the project. Keep the work scoped to documentation unless a tiny
sidecar correction is required, and run the repository's documentation checks when
you change files.
"""

DEFAULT_POLISH_PROMPT = """\
Inspect the documentation changes made by the update agent for {project}.

Verify every changed description against the current system behavior rather than
assuming it is true. Improve clarity for a new user, especially where terminology or
workflow ordering could be misunderstood. Keep edits scoped to documentation unless
a tiny sidecar correction is required, and run the repository's documentation checks
when you change files.
"""


def _target_label(runtime: BuiltinChopRuntime) -> str:
    target = runtime.context.target or {}
    for field_name in ("name", "project", "workspace"):
        value = target.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "the target project"


def _prompt_var(runtime: BuiltinChopRuntime, name: str, default: str) -> str:
    value = (runtime.context.vars or {}).get(name)
    if value is None:
        return default.format(project=_target_label(runtime)).strip()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"vars.{name} must be a non-blank string")
    return value.strip()


def _check_error(
    runtime: BuiltinChopRuntime,
    *,
    reason: str,
    detail: str,
) -> ChopResultBuilder:
    runtime.log.error(detail)
    result = runtime.emit_summary(
        {"targets": 0, "proposals": 0},
        reason=reason,
    )
    result.status = "check_error"
    return result


@builtin_chop("refresh_docs")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    target = runtime.context.target or {}
    workspace = target.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        return _check_error(
            runtime,
            reason="missing_target_workspace",
            detail=(
                "refresh_docs requires a non-blank target.workspace; configure "
                "for_each with the projects source or a literal workspace field"
            ),
        )

    try:
        update_prompt = _prompt_var(runtime, "prompt", DEFAULT_UPDATE_PROMPT)
        polish_prompt = _prompt_var(
            runtime,
            "polish_prompt",
            DEFAULT_POLISH_PROMPT,
        )
    except ValueError as error:
        return _check_error(
            runtime,
            reason="invalid_prompt_var",
            detail=str(error),
        )

    result = runtime.emit_summary({"targets": 1, "proposals": 2})
    result.propose(
        update_prompt,
        workspace.strip(),
        proposal_id="update",
    )
    result.propose(
        polish_prompt,
        workspace.strip(),
        proposal_id="polish",
        wait_on="update",
    )
    return result


def main() -> None:
    run_builtin_chop("refresh_docs")


if __name__ == "__main__":
    main()
