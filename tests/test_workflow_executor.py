"""Tests for WorkflowExecutor HITL, model, and VCS inheritance."""

import re
import tempfile
from unittest.mock import patch

from sase.llm_provider.messages import AIMessage
from sase.xprompt import WorkflowExecutor
from sase.xprompt.workflow_models import WorkflowStep

from tests._workflow_executor_helpers import _create_test_workflow


class TestShouldHitl:
    """Tests for the _should_hitl method on WorkflowExecutor."""

    def test_should_hitl_override_false_skips_hitl(self) -> None:
        """Test _should_hitl returns False when override is False."""
        step = WorkflowStep(name="s1", bash="echo ok", hitl=True)
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
                hitl_override=False,
            )
            assert executor._should_hitl(step) is False

    def test_inherited_model_override_beats_step_model_directive(self) -> None:
        """Workflow-level model override should take precedence for all steps."""
        step = WorkflowStep(name="s1", agent="%model:pro Respond with ok")
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            captured: dict[str, object] = {}

            def _fake_invoke_agent(prompt: str, **kwargs: object) -> AIMessage:
                del prompt
                captured["directives"] = kwargs.get("directives")
                return AIMessage(content="ok")

            with patch(
                "sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent
            ):
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                    inherited_model_override="gemini-3-flash-preview",
                )
                assert executor.execute() is True

            directives = captured.get("directives")
            assert directives is not None
            assert getattr(directives, "model", None) == "gemini-3-flash-preview"

    def test_prompt_step_chat_history_includes_step_metadata(self) -> None:
        """Prompt-step chat saves include execution context and step metadata."""
        step = WorkflowStep(name="review", agent="%model:codex/o3\nReview it")
        workflow = _create_test_workflow(name="workflow/main", steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            captured: dict[str, object] = {}

            def _fake_invoke_agent(prompt: str, **kwargs: object) -> AIMessage:
                captured["prompt"] = prompt
                captured["invoke_kwargs"] = kwargs
                return AIMessage(content="ok")

            def _fake_save_chat_history(**kwargs: object) -> str:
                captured["chat_kwargs"] = kwargs
                return "/tmp/chat.md"

            with (
                patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
                patch(
                    "sase.llm_provider.registry.resolve_model_provider",
                    return_value=("codex", "o3"),
                ),
                patch(
                    "sase.history.chat.save_chat_history",
                    side_effect=_fake_save_chat_history,
                ),
            ):
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={"cl_name": "feature_workspace"},
                    artifacts_dir=tmpdir,
                )
                assert executor.execute() is True

        invoke_kwargs = captured["invoke_kwargs"]
        assert isinstance(invoke_kwargs, dict)
        assert invoke_kwargs["branch_or_workspace"] == "feature_workspace"
        kwargs = captured["chat_kwargs"]
        assert isinstance(kwargs, dict)
        assert kwargs["agent"] == "review"
        assert kwargs["metadata_agent"] == "review"
        assert kwargs["metadata_model"] == "o3"
        assert kwargs["metadata_llm_provider"] == "codex"
        assert kwargs["branch_or_workspace"] == "feature_workspace"

    def test_inherited_vcs_tag_prefixes_bare_prompt_step(self) -> None:
        """Workflow step prompts inherit the wrapper VCS tag before expansion."""
        step = WorkflowStep(name="s1", agent="Fix it")
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            captured: dict[str, str] = {}

            def _fake_expand(
                self: WorkflowExecutor, prompt: str
            ) -> tuple[str, list[object], int]:
                del self
                captured["expanded_input"] = prompt
                return prompt, [], 0

            def _fake_invoke_agent(prompt: str, **_: object) -> AIMessage:
                captured["prompt"] = prompt
                return AIMessage(content="ok")

            with (
                patch.object(
                    WorkflowExecutor,
                    "_expand_embedded_workflows_in_prompt",
                    _fake_expand,
                ),
                patch(
                    "sase.xprompt.used_xprompts.write_used_xprompts",
                ) as mock_write_used,
                patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
            ):
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                    inherited_vcs_tag="#gh:sase ",
                )
                assert executor.execute() is True

        assert captured["expanded_input"] == "#gh:sase Fix it"
        assert captured["prompt"].rstrip("\n") == "#gh:sase Fix it"
        mock_write_used.assert_called_once_with(
            tmpdir,
            "#gh:sase Fix it",
            "s1",
            extra_xprompts={},
            step_only=True,
        )

    def test_inherited_vcs_tag_preserves_directives_and_segments(self) -> None:
        """Inherited VCS tags are inserted per segment after leading directives."""
        step = WorkflowStep(name="s1", agent="%w Follow up\n---\nSecond")
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            captured: dict[str, object] = {}

            def _fake_expand(
                self: WorkflowExecutor, prompt: str
            ) -> tuple[str, list[object], int]:
                del self
                captured["expanded_input"] = prompt
                return prompt, [], 0

            def _fake_invoke_agent(prompt: str, **kwargs: object) -> AIMessage:
                captured["prompt"] = prompt
                captured["directives"] = kwargs.get("directives")
                return AIMessage(content="ok")

            with (
                patch(
                    "sase.agent.names.get_most_recent_agent_name",
                    return_value="previous-agent",
                ),
                patch.object(
                    WorkflowExecutor,
                    "_expand_embedded_workflows_in_prompt",
                    _fake_expand,
                ),
                patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
            ):
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                    inherited_vcs_tag="#gh:sase ",
                )
                assert executor.execute() is True

        expected = " #gh:sase Follow up\n---\n#gh:sase Second"
        assert captured["expanded_input"] == expected
        directives = captured["directives"]
        assert directives is not None
        assert getattr(directives, "wait", None) == ["previous-agent"]

    def test_inherited_vcs_tag_does_not_override_explicit_step_ref(self) -> None:
        """A step-local workspace ref remains authoritative."""
        step = WorkflowStep(name="s1", agent="#git:other Fix it")
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            captured: dict[str, str] = {}

            def _fake_expand(
                self: WorkflowExecutor, prompt: str
            ) -> tuple[str, list[object], int]:
                del self
                captured["expanded_input"] = prompt
                return prompt, [], 0

            def _fake_invoke_agent(prompt: str, **_: object) -> AIMessage:
                captured["prompt"] = prompt
                return AIMessage(content="ok")

            ref_pattern = re.compile(
                r"#(?:gh|git|spy|cd)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)(?=\s|$)"
            )
            with (
                patch.object(
                    WorkflowExecutor,
                    "_expand_embedded_workflows_in_prompt",
                    _fake_expand,
                ),
                patch(
                    "sase.workspace_provider.get_ref_patterns",
                    return_value={"git": ref_pattern},
                ),
                patch(
                    "sase.xprompt.loader.get_known_project_workspaces",
                    return_value=set(),
                ),
                patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
            ):
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                    inherited_vcs_tag="#gh:sase ",
                )
                assert executor.execute() is True

        assert captured["expanded_input"] == "#git:other Fix it"
        assert captured["prompt"].rstrip("\n") == "#git:other Fix it"
