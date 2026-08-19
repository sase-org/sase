"""Shared helpers for run_agent_exec_retry tests."""

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.llm_provider.retry_config import ProviderRetryConfig

CLAUDE_WEEKLY_LIMIT = "You've hit your weekly limit · resets 8pm (America/New_York)"


@pytest.fixture(autouse=True)
def _restore_model_override_env() -> Iterator[None]:
    original = os.environ.get("SASE_MODEL_OVERRIDE")
    yield
    if original is None:
        os.environ.pop("SASE_MODEL_OVERRIDE", None)
    else:
        os.environ["SASE_MODEL_OVERRIDE"] = original


def make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260421_120000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260421_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model=None,
        agent_llm_provider="claude",
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def make_ctx_with_update_target(tmp_path: Path) -> AgentExecContext:
    """ctx with update_target set so prepare_workspace is eligible to fire."""
    return dataclasses.replace(make_ctx(tmp_path), update_target="origin/master")


def make_state(prompt: str = "Do the work.") -> LoopState:
    return LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir="",
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )


def config_with_nudge(
    nudge: str | None = "CONTINUATION NUDGE",
    max_retries: int = 2,
) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt=nudge,
    )
