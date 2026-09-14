"""Tests for building and decoding SASE_CHOP_* launch env vars."""

from __future__ import annotations

import hashlib

from sase.axe.chop_agents import (
    ENV_CHOP_LUMBERJACK,
    ENV_CHOP_NAME,
    ENV_CHOP_PROMPT_HASH,
    ENV_CHOP_RUN_ID,
    agent_meta_from_chop_env,
    build_chop_launch_env,
)


def test_build_chop_launch_env() -> None:
    """Both scheduled and one-shot paths can build matching chop env vars."""
    env = build_chop_launch_env(
        lumberjack_name="recurring",
        chop_name="my_agent",
        prompt="Review the repository.",
    )

    assert env[ENV_CHOP_LUMBERJACK] == "recurring"
    assert env[ENV_CHOP_NAME] == "my_agent"
    assert env[ENV_CHOP_RUN_ID]
    assert (
        env[ENV_CHOP_PROMPT_HASH]
        == hashlib.sha256(b"Review the repository.").hexdigest()
    )
    assert "SASE_AGENT_AUTO_DISMISS" not in env


def test_build_chop_launch_env_unique_run_ids() -> None:
    """Each invocation produces a fresh run id."""
    env_a = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    env_b = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    assert env_a[ENV_CHOP_RUN_ID] != env_b[ENV_CHOP_RUN_ID]


def test_agent_meta_from_chop_env() -> None:
    """Chop env vars are represented in agent_meta.json fields."""
    meta = agent_meta_from_chop_env(
        {
            ENV_CHOP_LUMBERJACK: "hooks",
            ENV_CHOP_NAME: "split",
            ENV_CHOP_RUN_ID: "run-1",
        }
    )

    assert meta == {
        "chop_lumberjack": "hooks",
        "chop_name": "split",
        "chop_run_id": "run-1",
    }
