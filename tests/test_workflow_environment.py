"""Tests for the workflow environment field.

Tests parsing, jinja2 rendering, and env var injection for the workflow-level
``environment`` field (sase-9.1: Phase 1).
"""

import os
import tempfile

from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_models import Workflow, WorkflowStep


class TestEnvironmentParsing:
    """Tests for parsing the environment field from workflow YAML."""

    def test_workflow_environment_default_empty(self) -> None:
        """Workflow without environment field defaults to empty dict."""
        wf = Workflow(name="test", steps=[WorkflowStep(name="s1", bash="true")])
        assert wf.environment == {}

    def test_workflow_environment_set(self) -> None:
        """Workflow with environment field stores the dict."""
        env = {"FOO": "bar", "BAZ": "qux"}
        wf = Workflow(
            name="test",
            steps=[WorkflowStep(name="s1", bash="true")],
            environment=env,
        )
        assert wf.environment == {"FOO": "bar", "BAZ": "qux"}

    def test_load_workflow_with_environment(self, tmp_path: str) -> None:
        """_load_workflow_from_file parses environment field."""
        from pathlib import Path

        from sase.xprompt.workflow_loader import _load_workflow_from_file

        wf_path = Path(tmp_path) / "env_test.yml"
        wf_path.write_text(
            """\
environment:
  MY_VAR: hello
  OTHER: world

steps:
  - name: s1
    bash: "echo ok"
""",
            encoding="utf-8",
        )
        wf = _load_workflow_from_file(wf_path)
        assert wf is not None
        assert wf.environment == {"MY_VAR": "hello", "OTHER": "world"}

    def test_load_workflow_without_environment(self, tmp_path: str) -> None:
        """_load_workflow_from_file defaults to empty environment."""
        from pathlib import Path

        from sase.xprompt.workflow_loader import _load_workflow_from_file

        wf_path = Path(tmp_path) / "no_env.yml"
        wf_path.write_text(
            """\
steps:
  - name: s1
    bash: "echo ok"
""",
            encoding="utf-8",
        )
        wf = _load_workflow_from_file(wf_path)
        assert wf is not None
        assert wf.environment == {}


class TestEnvironmentInjection:
    """Tests for env var injection during workflow execution."""

    def test_static_env_vars_set(self) -> None:
        """Static environment values are injected into os.environ."""
        step = WorkflowStep(name="check", bash="echo $TEST_SASE_STATIC")
        wf = Workflow(
            name="test",
            steps=[step],
            environment={"TEST_SASE_STATIC": "hello_world"},
        )

        old = os.environ.get("TEST_SASE_STATIC")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(workflow=wf, args={}, artifacts_dir=tmpdir)
                executor.execute()
            assert os.environ["TEST_SASE_STATIC"] == "hello_world"
        finally:
            if old is None:
                os.environ.pop("TEST_SASE_STATIC", None)
            else:
                os.environ["TEST_SASE_STATIC"] = old

    def test_jinja2_env_vars_rendered(self) -> None:
        """Environment values with Jinja2 templates are rendered against args."""
        from sase.xprompt.models import InputArg, InputType

        step = WorkflowStep(name="check", bash="echo ok")
        wf = Workflow(
            name="test",
            steps=[step],
            inputs=[InputArg(name="bug_id", type=InputType.INT, default=0)],
            environment={"TEST_SASE_BUG": "{{ bug_id }}"},
        )

        old = os.environ.get("TEST_SASE_BUG")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(
                    workflow=wf, args={"bug_id": 42}, artifacts_dir=tmpdir
                )
                executor.execute()
            assert os.environ["TEST_SASE_BUG"] == "42"
        finally:
            if old is None:
                os.environ.pop("TEST_SASE_BUG", None)
            else:
                os.environ["TEST_SASE_BUG"] = old

    def test_env_vars_overwrite_existing(self) -> None:
        """Workflow environment overwrites pre-existing env vars."""
        step = WorkflowStep(name="check", bash="echo ok")
        wf = Workflow(
            name="test",
            steps=[step],
            environment={"TEST_SASE_OVERWRITE": "new_value"},
        )

        os.environ["TEST_SASE_OVERWRITE"] = "old_value"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(workflow=wf, args={}, artifacts_dir=tmpdir)
                executor.execute()
            assert os.environ["TEST_SASE_OVERWRITE"] == "new_value"
        finally:
            os.environ.pop("TEST_SASE_OVERWRITE", None)

    def test_env_vars_available_to_bash_steps(self) -> None:
        """Environment variables are visible to subsequent bash steps."""
        from sase.xprompt.models import OutputSpec

        step = WorkflowStep(
            name="read_env",
            bash="echo result=$TEST_SASE_VISIBLE",
            output=OutputSpec(
                type="json_schema",
                schema={
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                },
            ),
        )
        wf = Workflow(
            name="test",
            steps=[step],
            environment={"TEST_SASE_VISIBLE": "from_env"},
        )

        old = os.environ.get("TEST_SASE_VISIBLE")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(workflow=wf, args={}, artifacts_dir=tmpdir)
                executor.execute()
            assert executor.context["read_env"]["result"] == "from_env"
        finally:
            if old is None:
                os.environ.pop("TEST_SASE_VISIBLE", None)
            else:
                os.environ["TEST_SASE_VISIBLE"] = old

    def test_empty_environment_no_side_effects(self) -> None:
        """Workflow with empty environment dict does not modify os.environ."""
        step = WorkflowStep(name="noop", bash="echo ok")
        wf = Workflow(name="test", steps=[step], environment={})

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(workflow=wf, args={}, artifacts_dir=tmpdir)
            # Should not raise or have side effects
            executor.execute()

    def test_multiple_env_vars(self) -> None:
        """Multiple environment variables are all set."""
        step = WorkflowStep(name="check", bash="echo ok")
        wf = Workflow(
            name="test",
            steps=[step],
            environment={
                "TEST_SASE_A": "alpha",
                "TEST_SASE_B": "beta",
                "TEST_SASE_C": "gamma",
            },
        )

        old_a = os.environ.get("TEST_SASE_A")
        old_b = os.environ.get("TEST_SASE_B")
        old_c = os.environ.get("TEST_SASE_C")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(workflow=wf, args={}, artifacts_dir=tmpdir)
                executor.execute()
            assert os.environ["TEST_SASE_A"] == "alpha"
            assert os.environ["TEST_SASE_B"] == "beta"
            assert os.environ["TEST_SASE_C"] == "gamma"
        finally:
            for key, old in [
                ("TEST_SASE_A", old_a),
                ("TEST_SASE_B", old_b),
                ("TEST_SASE_C", old_c),
            ]:
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
