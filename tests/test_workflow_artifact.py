"""Tests for artifact passing in xprompt workflows."""

import os
import tempfile

import pytest
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_loader import _parse_workflow_step
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)
from sase.xprompt.workflow_validator_checks import validate_cross_step_field_refs
from sase.xprompt.workflow_executor import WorkflowExecutor


# --- Phase 2: Parsing tests ---


class TestArtifactParsing:
    """Tests for parsing the artifact field on workflow steps."""

    def test_parse_artifact_stdout_on_bash_step(self) -> None:
        """artifact: stdout parsed correctly on a bash step."""
        step_data = {"name": "capture", "bash": "echo hello", "artifact": "stdout"}
        step = _parse_workflow_step(step_data, 0)
        assert step.artifact == "stdout"

    def test_parse_artifact_stdout_on_python_step(self) -> None:
        """artifact: stdout parsed correctly on a python step."""
        step_data = {
            "name": "capture",
            "python": "print('hello')",
            "artifact": "stdout",
        }
        step = _parse_workflow_step(step_data, 0)
        assert step.artifact == "stdout"

    def test_parse_no_artifact(self) -> None:
        """Step without artifact field has None."""
        step_data = {"name": "plain", "bash": "echo hello"}
        step = _parse_workflow_step(step_data, 0)
        assert step.artifact is None

    def test_parse_artifact_invalid_value(self) -> None:
        """artifact value other than 'stdout' raises error."""
        step_data = {"name": "bad", "bash": "echo hello", "artifact": "stderr"}
        with pytest.raises(WorkflowValidationError) as exc_info:
            _parse_workflow_step(step_data, 0)
        assert "'artifact' must be 'stdout'" in str(exc_info.value)

    def test_parse_artifact_on_prompt_part_rejected(self) -> None:
        """artifact on a prompt_part step raises error."""
        step_data = {
            "name": "bad",
            "prompt_part": "content",
            "artifact": "stdout",
        }
        with pytest.raises(WorkflowValidationError) as exc_info:
            _parse_workflow_step(step_data, 0)
        assert "'prompt_part' cannot have 'artifact'" in str(exc_info.value)

    def test_parse_artifact_on_agent_step_rejected(self) -> None:
        """artifact on an agent step raises error."""
        step_data = {"name": "bad", "agent": "do stuff", "artifact": "stdout"}
        with pytest.raises(WorkflowValidationError) as exc_info:
            _parse_workflow_step(step_data, 0)
        assert "'agent' cannot have 'artifact'" in str(exc_info.value)

    def test_parse_artifact_on_nested_step_rejected(self) -> None:
        """artifact on a nested (parallel) step raises error."""
        step_data = {"name": "bad", "bash": "echo hi", "artifact": "stdout"}
        with pytest.raises(WorkflowValidationError) as exc_info:
            _parse_workflow_step(step_data, 0, is_nested=True)
        assert "Nested step" in str(exc_info.value)
        assert "cannot have 'artifact'" in str(exc_info.value)


# --- Phase 3: Execution tests ---


class TestArtifactExecution:
    """Tests for artifact file creation during step execution."""

    def test_bash_step_artifact_created(self) -> None:
        """Bash step with artifact: stdout creates file and sets _artifact."""
        step = WorkflowStep(
            name="capture",
            bash="echo 'hello world'",
            artifact="stdout",
        )
        workflow = Workflow(name="test", steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True
            output = executor.context["capture"]
            assert "_artifact" in output
            artifact_path = output["_artifact"]
            assert os.path.basename(artifact_path) == "capture.stdout"
            assert os.path.isfile(artifact_path)
            with open(artifact_path) as f:
                content = f.read()
            assert "hello world" in content

    def test_python_step_artifact_created(self) -> None:
        """Python step with artifact: stdout creates file and sets _artifact."""
        step = WorkflowStep(
            name="gen",
            python="print('generated data')",
            artifact="stdout",
        )
        workflow = Workflow(name="test", steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True
            output = executor.context["gen"]
            assert "_artifact" in output
            artifact_path = output["_artifact"]
            assert os.path.basename(artifact_path) == "gen.stdout"
            with open(artifact_path) as f:
                content = f.read()
            assert "generated data" in content

    def test_empty_stdout_no_artifact(self) -> None:
        """Empty stdout does not create artifact file or _artifact key."""
        step = WorkflowStep(
            name="empty",
            bash="true",  # produces no output
            artifact="stdout",
        )
        workflow = Workflow(name="test", steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True
            output = executor.context["empty"]
            assert "_artifact" not in output
            assert not os.path.exists(os.path.join(tmpdir, "empty.stdout"))

    def test_artifact_coexists_with_output(self) -> None:
        """artifact and output both work: key=value parsed AND file saved."""
        step = WorkflowStep(
            name="both",
            bash="echo 'key=value'",
            artifact="stdout",
            output=OutputSpec(
                type="json_schema",
                schema={"properties": {"key": {"type": "string"}}},
            ),
        )
        workflow = Workflow(name="test", steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True
            output = executor.context["both"]
            # key=value parsing worked
            assert output["key"] == "value"
            # artifact also created
            assert "_artifact" in output
            assert os.path.isfile(output["_artifact"])

    def test_downstream_step_accesses_artifact(self) -> None:
        """Downstream step can reference {{ step._artifact }} path."""
        step1 = WorkflowStep(
            name="producer",
            bash="echo 'payload data'",
            artifact="stdout",
        )
        step2 = WorkflowStep(
            name="consumer",
            bash="cat '{{ producer._artifact }}'",
        )
        workflow = Workflow(name="test", steps=[step1, step2])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True


# --- Phase 4: Validator tests ---


class TestArtifactValidation:
    """Tests for cross-step field validation with _artifact."""

    def test_artifact_ref_passes_validation(self) -> None:
        """{{ step._artifact }} passes cross-step field validation."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    name="producer",
                    bash="echo data",
                    artifact="stdout",
                ),
                WorkflowStep(
                    name="consumer",
                    bash="cat {{ producer._artifact }}",
                ),
            ],
        )
        errors = validate_cross_step_field_refs(workflow)
        assert errors == []

    def test_artifact_with_output_ref_passes(self) -> None:
        """Step with both artifact and output: both _artifact and output fields valid."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    name="producer",
                    bash="echo key=val",
                    artifact="stdout",
                    output=OutputSpec(
                        type="json_schema",
                        schema={"properties": {"key": {"type": "string"}}},
                    ),
                ),
                WorkflowStep(
                    name="consumer",
                    bash="echo {{ producer.key }} {{ producer._artifact }}",
                ),
            ],
        )
        errors = validate_cross_step_field_refs(workflow)
        assert errors == []

    def test_artifact_typo_caught(self) -> None:
        """{{ step._atrifact }} (typo) is flagged when step has output schema."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    name="producer",
                    bash="echo key=val",
                    artifact="stdout",
                    output=OutputSpec(
                        type="json_schema",
                        schema={"properties": {"key": {"type": "string"}}},
                    ),
                ),
                WorkflowStep(
                    name="consumer",
                    bash="echo {{ producer._atrifact }}",
                ),
            ],
        )
        errors = validate_cross_step_field_refs(workflow)
        assert len(errors) == 1
        assert "_atrifact" in errors[0]
