"""Tests for workflow-local xprompts in workflow_loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_validator import validate_workflow


def test_parse_xprompt_entries_skips_invalid_values() -> None:
    """Test that non-string, non-dict values are skipped."""
    entries = {"good": "valid", "bad": 42, "also_bad": ["list"]}
    result = parse_xprompt_entries(entries, "test")

    assert len(result) == 1
    assert "good" in result


def test_workflow_local_xprompts_take_priority_over_globals() -> None:
    """Test that workflow-local xprompts take priority over global ones."""
    global_xprompt = XPrompt(
        name="_shared",
        content="Global content requiring {{ missing_arg }}.",
        inputs=[],
        source_path="config",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        workflow_content = """\
xprompts:
  _shared: "Local content with no args."
steps:
  - name: use_it
    prompt: "#_shared"
"""
        path = Path(tmp_dir) / "test.yml"
        path.write_text(workflow_content)

        workflow = _load_workflow_from_file(path)
        assert workflow is not None

        # Validate with global "_shared" that has issues, but local overrides it
        with patch(
            "sase.xprompt.workflow_validator.get_all_xprompts",
            return_value={"_shared": global_xprompt},
        ):
            # Should succeed because local xprompt (no args) overrides global
            validate_workflow(workflow)


def test_workflow_and_local_xprompt_descriptions_parse(tmp_path: Path) -> None:
    workflow_content = """\
description: Run a described workflow.
input:
  - name: prompt
    type: text
    description: User request for the workflow.
xprompts:
  _local:
    description: Local helper prompt.
    input:
      target:
        type: word
        description: Target name for the helper.
    content: "Review {{ target }}"
steps:
  - name: use_it
    prompt_part: "#_local"
"""
    path = tmp_path / "described.yml"
    path.write_text(workflow_content)

    workflow = _load_workflow_from_file(path)

    assert workflow is not None
    assert workflow.description == "Run a described workflow."
    assert len(workflow.inputs) == 1
    assert workflow.inputs[0].name == "prompt"
    assert workflow.inputs[0].description == "User request for the workflow."
    local = workflow.xprompts["_local"]
    assert local.description == "Local helper prompt."
    assert local.inputs[0].name == "target"
    assert local.inputs[0].description == "Target name for the helper."


def test_hidden_launcher_fixture_validates(tmp_path: Path) -> None:
    """Hidden launcher semantics use a synthetic fixture, not a bundled workflow."""
    path = tmp_path / "hidden_launcher.yml"
    path.write_text(
        "description: Synthetic detached launcher.\n"
        "hidden: true\n"
        "steps:\n"
        "  - name: launch\n"
        "    hidden: true\n"
        "    python: print('launched=true')\n",
        encoding="utf-8",
    )

    workflow = _load_workflow_from_file(path)

    assert workflow is not None
    assert workflow.hidden is True
    assert all(step.hidden is True for step in workflow.steps)
    validate_workflow(workflow)
