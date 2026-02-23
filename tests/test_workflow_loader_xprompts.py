"""Tests for workflow-local xprompts in workflow_loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.loader import parse_xprompt_entries
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
