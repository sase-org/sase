"""Shared environment hygiene for agent and system process boundaries."""

from collections.abc import MutableMapping


def scrub_agent_identity_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient per-agent identity and behavior variables from *env*."""
    for key in list(env):
        if key == "SASE_AGENT" or key.startswith("SASE_AGENT_"):
            env.pop(key, None)


def scrub_chop_context_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient per-chop/job context variables from *env*."""
    for key in list(env):
        if key.startswith(("SASE_CHOP_", "SASE_JOB_")):
            env.pop(key, None)


def scrub_proc_operation_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient proc-operation ownership variables from *env*."""
    for key in list(env):
        if key.startswith("SASE_PROC_"):
            env.pop(key, None)


def scrub_executor_ownership_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient executor-ownership variables from *env*.

    An agent is a new ownership root: nothing its shell runs was captured
    by an ancestor monitor, proc, or tool run. Drops ``SASE_TOOL_*``,
    ``SASE_MONITOR_*``, and ``SASE_PROC_*``. Kept separate from
    :func:`scrub_agent_identity_env`, which also runs inside monitor and
    proc supervisors where those owner variables are set on purpose.
    """
    for key in list(env):
        if key.startswith(("SASE_TOOL_", "SASE_MONITOR_", "SASE_PROC_")):
            env.pop(key, None)
