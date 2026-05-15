"""Tests for file panel features and workflow output_types extraction."""

import tempfile
import types
from typing import Any
from unittest.mock import MagicMock

from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_executor import WorkflowExecutor

# --- _get_output_types tests ---


def _make_executor_with_steps(
    steps: list[Any],
) -> WorkflowExecutor:
    """Create a WorkflowExecutor with given steps for testing."""
    workflow = MagicMock()
    workflow.steps = steps
    workflow.inputs = []
    workflow.name = "test"
    workflow.appears_as_agent.return_value = False

    with tempfile.TemporaryDirectory() as tmpdir:
        executor = WorkflowExecutor(
            workflow=workflow,
            args={},
            artifacts_dir=tmpdir,
        )
    return executor


def test_get_output_types_returns_none_when_no_properties() -> None:
    """Test that _get_output_types returns None when schema has no properties."""
    output_spec = OutputSpec(type="json_schema", schema={"type": "array"})
    step = MagicMock()
    step.name = "check"
    step.output = output_spec
    step.hidden = False
    step.condition = None
    step.for_loop = None
    step.repeat_config = None
    step.while_config = None
    step.parallel_config = None

    executor = _make_executor_with_steps([step])
    result = executor._get_output_types(0)

    assert result is None


# --- Path extraction from workflow state data tests ---


def _extract_diff_path_from_steps(steps_data: list[dict[str, Any]]) -> str | None:
    """Extract diff_path from workflow state steps data.

    This mirrors the logic in load_workflow_states().
    """
    diff_path = None
    for step_data in steps_data:
        output_types = step_data.get("output_types") or {}
        step_output = step_data.get("output")
        if output_types and isinstance(step_output, dict):
            for field_name, field_type in output_types.items():
                if field_type == "path":
                    path_value = step_output.get(field_name)
                    if path_value:
                        diff_path = str(path_value)
    return diff_path


def test_extract_diff_path_finds_path_typed_output() -> None:
    """Test that path-typed output fields are correctly extracted."""
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {
                "success": True,
                "cl_url": "http://cl/123",
                "diff_path": "/tmp/test.diff",
                "error": "",
            },
            "output_types": {
                "success": "bool",
                "cl_url": "line",
                "diff_path": "path",
                "error": "text",
            },
        }
    ]
    assert _extract_diff_path_from_steps(steps) == "/tmp/test.diff"


def test_extract_diff_path_returns_none_when_no_path_type() -> None:
    """Test that None is returned when no path-typed fields exist."""
    steps = [
        {
            "name": "check",
            "status": "completed",
            "output": {"has_changes": True},
            "output_types": {"has_changes": "bool"},
        }
    ]
    assert _extract_diff_path_from_steps(steps) is None


def test_extract_diff_path_returns_none_when_empty_path() -> None:
    """Test that empty path values are ignored."""
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {"diff_path": "", "error": "something failed"},
            "output_types": {"diff_path": "path", "error": "text"},
        }
    ]
    assert _extract_diff_path_from_steps(steps) is None


def test_extract_diff_path_returns_none_when_no_output_types() -> None:
    """Test backward compat: steps without output_types are skipped."""
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {"diff_path": "/tmp/test.diff"},
        }
    ]
    assert _extract_diff_path_from_steps(steps) is None


def test_extract_diff_path_uses_last_path() -> None:
    """Test that the last path-typed output wins when multiple steps have paths."""
    steps = [
        {
            "name": "save_response",
            "status": "completed",
            "output": {"data_file": "/tmp/data.json"},
            "output_types": {"data_file": "path"},
        },
        {
            "name": "create_cl",
            "status": "completed",
            "output": {"diff_path": "/tmp/final.diff"},
            "output_types": {"diff_path": "path"},
        },
    ]
    assert _extract_diff_path_from_steps(steps) == "/tmp/final.diff"


# --- display_static_file tests ---


def _make_render_panel() -> MagicMock:
    """Build a MagicMock panel pre-wired for the static-render helpers."""
    panel = MagicMock()
    panel.post_message = MagicMock()
    panel._has_displayed_content = False
    panel._file_list = []
    panel._current_file_index = 0
    panel._total_line_count = 0
    panel._visible_line_count = 0
    panel._base_trim_size = 0
    panel._is_trimmed = False
    panel._full_content = None
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._static_header_path = None
    panel._static_request_id = 0
    panel._static_worker = None

    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel._post_file_visibility = types.MethodType(
        AgentFilePanel._post_file_visibility, panel
    )
    panel._consume_image_cleanup_segments = types.MethodType(
        AgentFilePanel._consume_image_cleanup_segments, panel
    )
    panel._compute_trim_size = MagicMock(return_value=0)
    panel._count_lines = types.MethodType(AgentFilePanel._count_lines, panel)
    panel._post_trim_changed = MagicMock()
    return panel


def test_render_static_file_result_renders_content(tmp_path: Any) -> None:
    """The render helper produces the path header + syntax block on success."""
    from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER, AgentFilePanel
    from sase.ace.tui.widgets.file_panel._display import StaticReadResult

    assert _EXTENSION_TO_LEXER[".diff"] == "diff"

    diff_file = tmp_path / "test.diff"
    diff_file.write_text("--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-old\n+new\n")

    panel = _make_render_panel()
    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(diff_file),
        expanded_path=str(diff_file),
        status="ok",
        content=diff_file.read_text(),
        lexer="diff",
    )

    AgentFilePanel._render_static_file_result(panel, result)

    assert panel.update.called
    from rich.console import Group
    from rich.syntax import Syntax
    from rich.text import Text

    group = panel.update.call_args[0][0]
    assert isinstance(group, Group)
    renderables = list(group._renderables)
    assert len(renderables) == 3
    assert isinstance(renderables[0], Text)
    assert str(renderables[0]) == str(diff_file)
    assert isinstance(renderables[1], Text)
    assert str(renderables[1]) == ""
    assert isinstance(renderables[2], Syntax)
    panel.post_message.assert_called()
    assert panel.post_message.call_args[0][0].has_file is True


def test_render_static_file_result_handles_missing(tmp_path: Any) -> None:
    """Missing-file results post has_file=False."""
    from sase.ace.tui.widgets.file_panel import AgentFilePanel
    from sase.ace.tui.widgets.file_panel._display import StaticReadResult

    panel = _make_render_panel()
    missing = tmp_path / "nonexistent.diff"
    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(missing),
        expanded_path=str(missing),
        status="missing",
    )

    AgentFilePanel._render_static_file_result(panel, result)

    panel.post_message.assert_called()
    assert panel.post_message.call_args[0][0].has_file is False


def test_render_static_file_result_handles_empty(tmp_path: Any) -> None:
    """Empty-file results post has_file=False."""
    from sase.ace.tui.widgets.file_panel import AgentFilePanel
    from sase.ace.tui.widgets.file_panel._display import StaticReadResult

    panel = _make_render_panel()
    empty = tmp_path / "empty.diff"
    empty.write_text("")
    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(empty),
        expanded_path=str(empty),
        status="empty",
    )

    AgentFilePanel._render_static_file_result(panel, result)

    assert panel.post_message.call_args[0][0].has_file is False


def test_extension_to_lexer_mapping() -> None:
    """Test that the extension-to-lexer mapping includes common types."""
    from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER

    assert _EXTENSION_TO_LEXER[".diff"] == "diff"
    assert _EXTENSION_TO_LEXER[".py"] == "python"
    assert _EXTENSION_TO_LEXER[".json"] == "json"
    assert _EXTENSION_TO_LEXER[".yml"] == "yaml"
    assert _EXTENSION_TO_LEXER[".sh"] == "bash"
