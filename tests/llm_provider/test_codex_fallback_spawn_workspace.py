"""Commit finalizer spawn-workspace regression tests."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult
from tests.llm_provider._codex_fallback_helpers import commit_all, init_dirty_project


def test_finalizer_inspects_spawn_workspace_when_parent_env_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale parent env must not redirect the child's finalizer.

    Mirrors the old Codex fallback regression: the parent's leaked
    SASE_ACTIVE_PROJECT_DIR pointed at a clean repo, so the child inspected the
    wrong workspace. The spawn boundary now rewrites the child's canonical
    active project dir, and the common finalizer consumes that value.
    """
    from sase.running_field import ClaimResult
    from tests._workspace_provider_helpers import patch_git_metadata

    patch_git_metadata(monkeypatch)

    clean_parent = tmp_path / "parent-clean"
    dirty_workspace = tmp_path / "child-dirty"
    clean_parent.mkdir()
    init_dirty_project(dirty_workspace)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(clean_parent))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(clean_parent))

    captured_env: dict[str, str] = {}

    def fake_spawn(
        _prepared: object,
        *,
        env: dict[str, str],
        claim_callback: Callable[[int], bool] | None = None,
    ) -> int:
        captured_env.update(env)
        if claim_callback is not None:
            claim_callback(12345)
        return 12345

    from sase.agent.launcher import spawn_agent_subprocess

    with (
        patch(
            "sase.core.paths.sharded_path",
            return_value=str(tmp_path / "agent.log"),
        ),
        patch(
            "sase.core.agent_launch_facade.spawn_prepared_agent_process",
            side_effect=fake_spawn,
        ),
        patch(
            "sase.running_field.claim_workspace",
            return_value=ClaimResult(success=True),
        ),
        patch(
            "sase.running_field.transfer_workspace_claim",
            return_value=ClaimResult(success=True),
        ),
        patch(
            "sase.config.require_agent_owner_identity",
            return_value=AgentOwnerIdentity("alice", "athena"),
        ),
        patch("sase.axe.chop_agents.record_chop_agent_launch_from_env"),
    ):
        spawn_agent_subprocess(
            cl_name="home",
            project_file=str(tmp_path / "home.sase"),
            workspace_dir=str(dirty_workspace),
            workspace_num=101,
            workflow_name="ace(run)-ts",
            prompt="#git:home do work",
            timestamp="20260512190000",
            project_name="home",
            is_home_mode=False,
            vcs_ref=("git", "home"),
        )

    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    if "SASE_ACTIVE_PROJECT_DIR" in captured_env:
        monkeypatch.setenv(
            "SASE_ACTIVE_PROJECT_DIR", captured_env["SASE_ACTIVE_PROJECT_DIR"]
        )
    assert "CODEX_PROJECT_DIR" not in captured_env
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260512_183950")

    inspected: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        inspected["project_dir"] = project_dir
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        return (True, changed_files, "commit", "details body")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        fake_build,
    )
    provider = MagicMock()

    def invoke(*_args: object, **_kwargs: object) -> InvokeResult:
        commit_all(dirty_workspace)
        return InvokeResult(content="follow-up")

    provider.invoke.side_effect = invoke

    result = run_commit_finalizer(
        provider=provider,
        original_prompt="prompt",
        invoke_result=InvokeResult(content="response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    assert inspected["project_dir"] == str(dirty_workspace)
    assert provider.invoke.call_count == 1
    assert result.content == "response\n\nfollow-up"
