"""Composition regression: launch preflight -> typed fork wait ->
runner admission when a `#fork` parent is already terminally failed.

Reproduces the `sase-sq.7.1.2.f0` / `sase-sq.7.1.2.f0.f0` shape from plan
``202608/repair_failed_agent_fork_launch.md``: a `#fork:<name>` parent dies
before writing a transcript. Launch preflight's cheap, lexical
``has_deferred_start_directive()`` scan cannot see that, so it still
classifies the launch as deferred. Directive extraction binds the failed
source as a terminal-aware fork dependency; the wait barrier resolves it
immediately, and the runner must still admit the run and claim a real
workspace rather than crashing in bootstrap or bypassing an unrelated
user-authored wait.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.axe.run_agent_wait_deps import initial_dependencies_resolved
from sase.core.dismissed_agent_completion import FAILURE_OUTCOME
from sase.linked_repos import LinkedRepoResolution
from sase.xprompt.directives import has_deferred_start_directive

from tests._agent_names_fixtures import make_agent as _make_agent
from tests._axe_run_agent_runner_retry_helpers import (
    BOOTSTRAP,
    LAUNCH,
    RUNNER,
    base_patches,
    exec_result,
    run_main,
)


def _extract_for_fork_parent(tmp_path: Path, target_name: str, *, prompt: str) -> Any:
    workspace_dir = tmp_path / "extract-workspace"
    artifacts_dir = tmp_path / "extract-artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        return extract_directives_and_write_meta(
            prompt,
            str(workspace_dir),
            str(artifacts_dir),
            output_path=str(tmp_path / "out.log"),
            raw_resolved_prompt=f"{prompt}\n#fork:{target_name}",
        )


class TestFailedForkParentAdmission:
    def test_preflight_and_extraction_agree_on_a_failed_fork_parent(
        self, tmp_path: Path
    ) -> None:
        """No-transcript failed parent: preflight defers, extraction records
        a terminal-aware fork dependency that is already resolved."""
        parent_dir = _make_agent(
            tmp_path,
            "proj",
            "run1",
            "parent-agent",
            done=True,
            outcome=FAILURE_OUTCOME,
        )
        raw_prompt = "Do work\n#fork:parent-agent"

        assert has_deferred_start_directive(raw_prompt) is True

        with patch.object(Path, "home", return_value=tmp_path):
            info = _extract_for_fork_parent(tmp_path, "parent-agent", prompt="Do work")
            resolved = initial_dependencies_resolved(
                info.wait_names,
                info.wait_identity_deps,
                wait_fork_sources=info.wait_fork_sources,
                project_name="proj",
                artifacts_dir=str(tmp_path / "child-artifacts"),
            )

        assert info.wait_names == ["parent-agent"]
        assert info.wait_fork_sources == [
            {
                "kind": "agent",
                "name": "parent-agent",
                "artifact_dir": str(parent_dir),
                "timestamp": "run1",
                "project_name": "proj",
            }
        ]
        assert info.wait_beads == []
        assert info.wait_duration is None
        assert info.wait_until is None
        assert info.wait_runners is None
        assert info.wait_priority is None
        assert resolved

    def test_explicit_wait_on_failed_fork_parent_is_not_dropped(
        self, tmp_path: Path
    ) -> None:
        """A user-authored `%wait:<name>` survives with success-only
        semantics even though the same name is also an implicit `#fork` wait."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "parent-agent",
            done=True,
            outcome=FAILURE_OUTCOME,
        )

        with patch.object(Path, "home", return_value=tmp_path):
            info = _extract_for_fork_parent(
                tmp_path, "parent-agent", prompt="%wait:parent-agent\nDo work"
            )

        assert "parent-agent" in info.wait_names
        assert info.wait_fork_sources == []

    def test_runner_admits_and_claims_real_workspace_for_failed_fork_parent(
        self, tmp_path: Path
    ) -> None:
        """End to end: the runner reaches the run loop with a real,
        nonzero workspace instead of crashing in bootstrap or running the
        model in the placeholder workspace."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "parent-agent",
            done=True,
            outcome=FAILURE_OUTCOME,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            info = _extract_for_fork_parent(tmp_path, "parent-agent", prompt="Do work")
        assert info.wait_fork_sources  # sanity: reproduces typed terminal wait shape

        artifacts_dir = str(tmp_path / "run-artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[str] = []

        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=info
        )
        wait_for_dependencies = MagicMock(
            side_effect=lambda *_args, **_kwargs: events.append("wait") or False
        )
        write_error = MagicMock()

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 5, str(real_ws)

        def run_loop(ctx: Any, _prompt: str) -> Any:
            events.append("run")
            assert ctx.workspace_num == 5
            assert ctx.workspace_num != 0
            assert ctx.workspace_dir == str(real_ws)
            assert ctx.workspace_dir != str(placeholder_ws)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_dependencies
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{LAUNCH}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{LAUNCH}.run_execution_loop"] = MagicMock(side_effect=run_loop)
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", "claim", "run"]
        wait_for_dependencies.assert_called_once()
        write_error.assert_not_called()
