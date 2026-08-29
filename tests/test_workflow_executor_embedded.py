"""Tests for embedded workflow expansion in WorkflowExecutor."""

import tempfile
from unittest.mock import patch

import pytest
from sase.xprompt import WorkflowExecutor
from sase.xprompt.workflow_models import Workflow, WorkflowExecutionError, WorkflowStep

from tests._workflow_executor_helpers import _create_test_workflow


class TestEmbeddedWorkflowExpansion:
    """Tests for embedded workflow expansion in prompts."""

    def test_embedded_workflow_hashes_inline_gets_newlines(self) -> None:
        """Test that ### content gets \\n\\n prepended when not at line start."""
        workflow_with_hashes = Workflow(
            name="inject_workflow",
            steps=[
                WorkflowStep(
                    name="inject",
                    prompt_part="### Section Header\nSection content",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            main_workflow = _create_test_workflow()
            executor = WorkflowExecutor(
                workflow=main_workflow,
                args={},
                artifacts_dir=tmpdir,
            )

            with patch("sase.xprompt.loader.get_all_workflows") as mock_get_workflows:
                mock_get_workflows.return_value = {
                    "inject_workflow": workflow_with_hashes
                }

                # Test case: workflow ref inline (not at line start)
                prompt = "Context text. #inject_workflow"
                expanded, _, _ = executor._expand_embedded_workflows_in_prompt(prompt)

                # Should prepend \n\n before the ### content
                assert "\n\n### Section Header" in expanded

    def test_standalone_workflow_reference_errors_in_inline_prompt(self) -> None:
        """Standalone workflows cannot pass through as literal inline text."""
        standalone = Workflow(
            name="deploy",
            steps=[WorkflowStep(name="run", bash="echo deploy")],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=_create_test_workflow(),
                args={},
                artifacts_dir=tmpdir,
            )

            with patch(
                "sase.xprompt.loader.get_all_workflows",
                return_value={"deploy": standalone},
            ):
                with pytest.raises(WorkflowExecutionError, match=r"Use `#!deploy`"):
                    executor._expand_embedded_workflows_in_prompt("Run #deploy now")

    def test_bang_embeddable_workflow_reference_errors_in_inline_prompt(self) -> None:
        """The #! marker is reserved for standalone workflows."""
        embeddable = Workflow(
            name="commit",
            steps=[WorkflowStep(name="prompt", prompt_part="Commit instructions")],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=_create_test_workflow(),
                args={},
                artifacts_dir=tmpdir,
            )

            with patch(
                "sase.xprompt.loader.get_all_workflows",
                return_value={"commit": embeddable},
            ):
                with pytest.raises(
                    WorkflowExecutionError,
                    match=r"only standalone workflows use `#!`",
                ):
                    executor._expand_embedded_workflows_in_prompt("Run #!commit now")
