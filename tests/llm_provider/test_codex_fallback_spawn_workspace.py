"""Codex commit-stop fallback spawn-workspace regression tests."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import CodexProvider
from tests.llm_provider._codex_fallback_helpers import (
    isolate_fallback_markers,
    set_sase_session,
)


def test_codex_fallback_inspects_spawn_workspace_when_parent_env_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end regression: stale parent env must not redirect the fallback.

    Mirrors the sase-39.1 bug: parent's leaked SASE_ACTIVE_PROJECT_DIR pointed
    at a clean repo, so the child's commit-stop fallback skipped with
    no_changes. After the spawn-boundary rewrite, the child's env reflects the
    child's actual workspace; the fallback inspects that workspace and emits a
    commit block when it's dirty.
    """
    from sase.running_field import ClaimResult
    from tests._cd_launch_resolution_helpers import patch_cd_git_metadata

    patch_cd_git_metadata(monkeypatch)

    clean_parent = tmp_path / "parent-clean"
    dirty_workspace = tmp_path / "child-dirty"
    clean_parent.mkdir()
    dirty_workspace.mkdir()
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

    # Simulate the spawned child by applying the captured env. The child's
    # resolver should consult its own env, not the parent's.
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    if "SASE_ACTIVE_PROJECT_DIR" in captured_env:
        monkeypatch.setenv(
            "SASE_ACTIVE_PROJECT_DIR", captured_env["SASE_ACTIVE_PROJECT_DIR"]
        )
    assert "CODEX_PROJECT_DIR" not in captured_env

    isolate_fallback_markers(monkeypatch, tmp_path)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    if "SASE_ACTIVE_PROJECT_DIR" in captured_env:
        monkeypatch.setenv(
            "SASE_ACTIVE_PROJECT_DIR", captured_env["SASE_ACTIVE_PROJECT_DIR"]
        )
    set_sase_session(monkeypatch, "260512_183950")

    inspected: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        inspected["project_dir"] = project_dir
        return (True, ["src/foo.py"], "commit", "details body")

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    emitted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: emitted.append((event, kwargs)),
    )

    popen_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("sase.llm_provider.codex.subprocess.Popen", popen_mock)
    monkeypatch.setattr(
        "sase.llm_provider.codex.stream_and_parse_codex_json_output",
        lambda *a, **k: ("follow-up", "", 0),
    )

    provider = CodexProvider()
    result = provider._maybe_run_commit_fallback_turn(
        base_args=["codex"],
        original_prompt="prompt",
        accumulated_response="response",
        suppress_output=True,
    )

    assert inspected["project_dir"] == str(dirty_workspace)
    assert result is not None
    assert any(event == "codex_fallback_block_emitted" for event, _ in emitted)
