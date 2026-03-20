"""Tests for step imports (use: field) in workflow loading."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.xprompt.workflow_loader import (
    _load_step_definition,
    _load_workflow_from_file,
    _resolve_step_imports,
)


@pytest.fixture
def step_dir(tmp_path: Path) -> Path:
    """Create a temporary steps directory with a sample step definition."""
    steps_dir = tmp_path / "steps" / "shared"
    steps_dir.mkdir(parents=True)

    step_file = steps_dir / "check_changes.yml"
    step_file.write_text(
        "hidden: true\n"
        "python: |\n"
        "  print('has_changes=true')\n"
        "output: { has_changes: bool }\n"
    )
    return tmp_path / "steps"


@pytest.fixture
def _patch_search_dirs(step_dir: Path) -> Generator[None]:
    """Patch _get_step_search_dirs to return the temp steps directory."""
    with patch(
        "sase.xprompt.workflow_loader._get_step_search_dirs",
        return_value=[step_dir],
    ):
        yield


class TestLoadStepDefinition:
    """Tests for _load_step_definition."""

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_load_existing_step(self) -> None:
        result = _load_step_definition("shared/check_changes")
        assert result is not None
        assert result["hidden"] is True
        assert "python" in result
        assert "output" in result

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_load_missing_step_returns_none(self) -> None:
        result = _load_step_definition("shared/nonexistent")
        assert result is None

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_rejects_parent_path_traversal(self) -> None:
        result = _load_step_definition("../etc/passwd")
        assert result is None

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_rejects_absolute_path(self) -> None:
        result = _load_step_definition("/etc/passwd")
        assert result is None

    def test_yaml_extension_fallback(self, step_dir: Path) -> None:
        """Test that .yaml extension is tried when .yml doesn't exist."""
        yaml_dir = step_dir / "alt"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "my_step.yaml"
        yaml_file.write_text("bash: echo hello\n")

        with patch(
            "sase.xprompt.workflow_loader._get_step_search_dirs",
            return_value=[step_dir],
        ):
            result = _load_step_definition("alt/my_step")
        assert result is not None
        assert result["bash"] == "echo hello"

    def test_priority_order(self, tmp_path: Path) -> None:
        """First matching directory wins."""
        dir_a = tmp_path / "a" / "steps" / "shared"
        dir_b = tmp_path / "b" / "steps" / "shared"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "step.yml").write_text("bash: echo a\n")
        (dir_b / "step.yml").write_text("bash: echo b\n")

        with patch(
            "sase.xprompt.workflow_loader._get_step_search_dirs",
            return_value=[tmp_path / "a" / "steps", tmp_path / "b" / "steps"],
        ):
            result = _load_step_definition("shared/step")
        assert result is not None
        assert result["bash"] == "echo a"


class TestResolveStepImports:
    """Tests for _resolve_step_imports."""

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_resolve_use_field(self) -> None:
        step_data = {"name": "check_changes", "use": "shared/check_changes"}
        result = _resolve_step_imports(step_data)
        assert result is not None
        assert "use" not in result
        assert result["name"] == "check_changes"
        assert result["hidden"] is True
        assert "python" in result

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_local_fields_override_base(self) -> None:
        step_data = {
            "name": "my_check",
            "use": "shared/check_changes",
            "hidden": False,
        }
        result = _resolve_step_imports(step_data)
        assert result is not None
        assert result["name"] == "my_check"
        assert result["hidden"] is False  # Local override
        assert "python" in result  # From base

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_missing_import_returns_none(self) -> None:
        step_data = {"name": "bad", "use": "shared/nonexistent"}
        result = _resolve_step_imports(step_data)
        assert result is None

    def test_passthrough_without_use(self) -> None:
        """Step data without use: is returned unchanged."""
        step_data = {"name": "plain", "bash": "echo hello"}
        result = _resolve_step_imports(step_data)
        assert result == step_data

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_resolve_nested_parallel_use(self, step_dir: Path) -> None:
        """use: works in nested parallel steps."""
        step_data = {
            "name": "par",
            "parallel": [
                {"name": "a", "use": "shared/check_changes"},
                {"name": "b", "bash": "echo b"},
            ],
        }
        result = _resolve_step_imports(step_data)
        assert result is not None
        assert "python" in result["parallel"][0]
        assert result["parallel"][1]["bash"] == "echo b"


class TestLoadWorkflowWithStepImports:
    """End-to-end tests for loading workflows with use: steps."""

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_workflow_with_use_step(self, tmp_path: Path) -> None:
        wf_file = tmp_path / "test_wf.yml"
        wf_file.write_text(
            "steps:\n"
            "  - name: check\n"
            "    use: shared/check_changes\n"
            "  - name: act\n"
            '    if: "{{ check.has_changes }}"\n'
            "    bash: echo acting\n"
        )
        workflow = _load_workflow_from_file(wf_file)
        assert workflow is not None
        assert len(workflow.steps) == 2
        assert workflow.steps[0].name == "check"
        assert workflow.steps[0].is_python_step()
        assert workflow.steps[0].hidden is True
        assert workflow.steps[0].output is not None

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_workflow_use_with_local_override(self, tmp_path: Path) -> None:
        wf_file = tmp_path / "test_wf.yml"
        wf_file.write_text(
            "steps:\n"
            "  - name: check\n"
            "    use: shared/check_changes\n"
            "    hidden: false\n"
        )
        workflow = _load_workflow_from_file(wf_file)
        assert workflow is not None
        assert workflow.steps[0].hidden is False  # Overridden

    @pytest.mark.usefixtures("_patch_search_dirs")
    def test_workflow_missing_use_skips_step(self, tmp_path: Path) -> None:
        wf_file = tmp_path / "test_wf.yml"
        wf_file.write_text(
            "steps:\n"
            "  - name: bad\n"
            "    use: shared/nonexistent\n"
            "  - name: ok\n"
            "    bash: echo ok\n"
        )
        workflow = _load_workflow_from_file(wf_file)
        assert workflow is not None
        assert len(workflow.steps) == 1
        assert workflow.steps[0].name == "ok"
