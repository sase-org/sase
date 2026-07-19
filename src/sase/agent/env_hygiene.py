"""Shared environment hygiene for agent and system process boundaries."""

from collections.abc import MutableMapping


def scrub_agent_identity_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient per-agent identity and behavior variables from *env*."""
    for key in list(env):
        if key == "SASE_AGENT" or key.startswith("SASE_AGENT_"):
            env.pop(key, None)


def scrub_chop_context_env(env: MutableMapping[str, str]) -> None:
    """Remove ambient per-chop context variables from *env*."""
    for key in list(env):
        if key.startswith("SASE_CHOP_"):
            env.pop(key, None)
