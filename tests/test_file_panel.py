"""Tests for file panel features and workflow output_types extraction."""

import tempfile
import types
from datetime import datetime
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

    Mirrors the backward "explicit diff_path output" search in
    load_workflow_states(), sharing the real extraction helper so these tests
    track production semantics: only a field literally named ``diff_path``
    counts as a diff.
    """
    from sase.ace.tui.models._loaders._diff_path import diff_path_from_step_output

    for step_data in reversed(steps_data):
        diff_path = diff_path_from_step_output(step_data.get("output"))
        if diff_path:
            return diff_path
    return None


def test_extract_diff_path_finds_explicit_diff_path_output() -> None:
    """Test that an explicit ``diff_path`` output field is extracted."""
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {
                "success": True,
                "pr_url": "http://cl/123",
                "diff_path": "/tmp/test.diff",
                "error": "",
            },
            "output_types": {
                "success": "bool",
                "pr_url": "line",
                "diff_path": "path",
                "error": "text",
            },
        }
    ]
    assert _extract_diff_path_from_steps(steps) == "/tmp/test.diff"


def test_extract_diff_path_returns_none_when_no_diff_path_field() -> None:
    """Test that None is returned when no ``diff_path`` field exists."""
    steps = [
        {
            "name": "check",
            "status": "completed",
            "output": {"has_changes": True},
            "output_types": {"has_changes": "bool"},
        }
    ]
    assert _extract_diff_path_from_steps(steps) is None


def test_extract_diff_path_ignores_non_diff_path_typed_output() -> None:
    """A generic ``"path"``-typed field (e.g. #sshot's PNG) is not a diff."""
    steps = [
        {
            "name": "fetch",
            "status": "completed",
            "output": {"local_path": "/tmp/screenshots/shot.png"},
            "output_types": {"local_path": "path"},
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


def test_extract_diff_path_finds_explicit_key_without_output_types() -> None:
    """An explicit ``diff_path`` output needs no output_types to be honored."""
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {"diff_path": "/tmp/test.diff"},
        }
    ]
    assert _extract_diff_path_from_steps(steps) == "/tmp/test.diff"


def test_extract_diff_path_skips_later_non_diff_path_output() -> None:
    """A later path-typed artifact must not shadow an earlier real diff.

    Regression for the #sshot crash: backward search returns the explicit
    ``diff_path`` from an earlier step rather than promoting a later
    screenshot's ``local_path``.
    """
    steps = [
        {
            "name": "create_cl",
            "status": "completed",
            "output": {"diff_path": "/tmp/final.diff"},
            "output_types": {"diff_path": "path"},
        },
        {
            "name": "fetch",
            "status": "completed",
            "output": {"local_path": "/tmp/screenshots/shot.png"},
            "output_types": {"local_path": "path"},
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
    panel._is_content_capped = False
    panel._full_content = None
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._content_fetched_at = None
    panel._static_header_path = None
    panel._linked_repo_name = None
    panel._linked_workspace_dir = None
    panel._linked_fetched_at = None
    panel._static_request_id = 0
    panel._static_worker = None

    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel._build_linked_banner = types.MethodType(
        AgentFilePanel._build_linked_banner, panel
    )
    panel._post_file_visibility = types.MethodType(
        AgentFilePanel._post_file_visibility, panel
    )
    panel._consume_image_cleanup_segments = types.MethodType(
        AgentFilePanel._consume_image_cleanup_segments, panel
    )
    panel._count_lines = types.MethodType(AgentFilePanel._count_lines, panel)
    panel._timestamp_header = types.MethodType(AgentFilePanel._timestamp_header, panel)
    # Body renders go through ``_update_body`` (the scroll-anchor seam), not
    # ``update`` directly. Leave the MagicMock in place so tests can inspect
    # the renderable that production handed the seam.
    panel._update_body = MagicMock()
    panel._render_full_content = types.MethodType(
        AgentFilePanel._render_full_content, panel
    )
    panel._post_line_count_changed = types.MethodType(
        AgentFilePanel._post_line_count_changed, panel
    )
    from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache

    panel._content_render_cache = LazySyntaxRenderCache(max_entries=2)
    return panel


def _last_updated_body(panel: MagicMock) -> Any:
    """Return the renderable last routed through ``_update_body``."""
    assert panel._update_body.called
    assert panel._update_body.call_args is not None
    return panel._update_body.call_args[0][0]


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

    from rich.console import Group
    from rich.text import Text

    group = _last_updated_body(panel)
    assert isinstance(group, Group)
    renderables = list(group._renderables)
    assert len(renderables) == 3
    assert isinstance(renderables[0], Text)
    assert str(renderables[0]) == str(diff_file)
    assert isinstance(renderables[1], Text)
    assert str(renderables[1]) == ""
    assert getattr(renderables[2], "code", None) == diff_file.read_text()
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
    visibility = next(
        call.args[0]
        for call in panel.post_message.call_args_list
        if hasattr(call.args[0], "has_file")
    )
    assert visibility.has_file is False


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

    visibility = next(
        call.args[0]
        for call in panel.post_message.call_args_list
        if hasattr(call.args[0], "has_file")
    )
    assert visibility.has_file is False


def test_extension_to_lexer_mapping() -> None:
    """Test that the extension-to-lexer mapping includes common types."""
    from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER

    assert _EXTENSION_TO_LEXER[".diff"] == "diff"
    assert _EXTENSION_TO_LEXER[".py"] == "python"
    assert _EXTENSION_TO_LEXER[".json"] == "json"
    assert _EXTENSION_TO_LEXER[".yml"] == "yaml"
    assert _EXTENSION_TO_LEXER[".sh"] == "bash"


def test_display_linked_diff_renders_banner_and_raw_content() -> None:
    """Linked diff pages render a repo banner and keep raw diff for copy/edit."""
    from rich.console import Group
    from rich.text import Text

    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel = _make_render_panel()
    diff_text = "diff --git a/lib.py b/lib.py\n--- a/lib.py\n+++ b/lib.py\n+new\n"

    AgentFilePanel.display_linked_diff(
        panel,
        "sase-core",
        "/tmp/sase-core",
        diff_text,
        datetime(2024, 1, 1, 12, 30, 0),
    )

    assert panel._content_mode == "linked_diff"
    assert panel._full_content_lexer == "diff"
    assert panel._full_content == diff_text
    assert panel._last_file_content == diff_text
    visibility = next(
        call.args[0]
        for call in panel.post_message.call_args_list
        if hasattr(call.args[0], "has_file")
    )
    assert visibility.has_file is True

    group = _last_updated_body(panel)
    assert isinstance(group, Group)
    renderables = list(group._renderables)
    assert isinstance(renderables[0], Text)
    assert "▣ sase-core · linked repo" in str(renderables[0])
    assert "/tmp/sase-core · fetched 12:30:00" in str(renderables[0])


def test_live_diff_renders_all_lines_and_posts_line_count() -> None:
    from sase.ace.tui.widgets.file_panel import AgentFilePanel, FileLineCountChanged

    panel = _make_render_panel()
    diff_text = "+one\n+two\n+three\n"

    AgentFilePanel._display_file_with_timestamp(
        panel,
        diff_text,
        datetime(2024, 1, 1, 12, 30, 0),
    )

    assert panel._full_content == diff_text
    assert panel._visible_line_count == panel._total_line_count == 3
    assert "more lines below" not in str(_last_updated_body(panel))
    messages = [call.args[0] for call in panel.post_message.call_args_list]
    line_count = next(m for m in messages if isinstance(m, FileLineCountChanged))
    assert line_count.visible_lines == line_count.total_lines == 3
    assert line_count.capped is False


def test_live_diff_timestamp_refresh_reuses_cached_body() -> None:
    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel = _make_render_panel()
    diff_text = "+one\n+two\n"
    AgentFilePanel._display_file_with_timestamp(
        panel,
        diff_text,
        datetime(2024, 1, 1, 12, 30, 0),
    )
    first_group = _last_updated_body(panel)
    first_body = list(first_group._renderables)[2]

    panel._content_fetched_at = datetime(2024, 1, 1, 12, 31, 0)
    AgentFilePanel._render_full_content(panel)
    second_group = _last_updated_body(panel)
    second_body = list(second_group._renderables)[2]

    assert second_body is first_body
    assert panel._content_render_cache.hits == 1


def test_file_panel_pathological_cap_posts_explicit_range() -> None:
    from sase.ace.tui.util.lazy_syntax import FILE_PANEL_MAX_RENDER_LINES
    from sase.ace.tui.widgets.file_panel import AgentFilePanel, FileLineCountChanged

    panel = _make_render_panel()
    total = FILE_PANEL_MAX_RENDER_LINES + 2
    diff_text = "\n".join(f"+line {index}" for index in range(total))
    AgentFilePanel._display_file_with_timestamp(
        panel,
        diff_text,
        datetime(2024, 1, 1, 12, 30, 0),
    )

    assert panel._visible_line_count == FILE_PANEL_MAX_RENDER_LINES
    assert panel._total_line_count == total
    assert panel._is_content_capped
    messages = [call.args[0] for call in panel.post_message.call_args_list]
    line_count = next(m for m in messages if isinstance(m, FileLineCountChanged))
    assert line_count.capped is True
    body = list(_last_updated_body(panel)._renderables)[2]
    assert "… 2 more lines — press E to open in editor" in str(
        body._renderable.renderables[2]
    )


def test_zoom_file_cap_subtitle_points_to_editor() -> None:
    from sase.ace.tui.modals.zoom_panel_events import on_file_line_count_changed
    from sase.ace.tui.widgets.file_panel import FileLineCountChanged

    modal = MagicMock()
    scroll = MagicMock()
    modal.query_one.return_value = scroll
    message = FileLineCountChanged(
        visible_lines=5_000,
        total_lines=6_000,
        capped=True,
    )

    on_file_line_count_changed(modal, message)

    assert str(scroll.border_subtitle) == "1-5000 of 6000 lines (E: editor)"


def test_linked_diff_full_rerender_keeps_banner() -> None:
    """Full re-renders keep linked diffs with their banner intact."""
    from rich.console import Group
    from rich.text import Text

    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel = _make_render_panel()
    panel._content_mode = "linked_diff"
    panel._full_content = "+one\n+two\n+three\n"
    panel._full_content_lexer = "diff"
    panel._linked_repo_name = "sase-core"
    panel._linked_workspace_dir = "/tmp/sase-core"
    panel._linked_fetched_at = datetime(2024, 1, 1, 12, 30, 0)

    AgentFilePanel._render_full_content(panel)

    group = _last_updated_body(panel)
    assert isinstance(group, Group)
    renderables = list(group._renderables)
    assert isinstance(renderables[0], Text)
    assert "▣ sase-core · linked repo" in str(renderables[0])
    assert "more lines below" not in str(group)
