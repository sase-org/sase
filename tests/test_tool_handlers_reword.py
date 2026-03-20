"""Tests for handle_reword_prepare, reword_execute_task, and helpers."""

import os
from unittest.mock import MagicMock, patch

from sase.ace.handlers.reword import (
    _add_prettier_ignore_before_tags,
    _fetch_cl_description,
    _open_editor_with_content,
    handle_reword_prepare,
    reword_execute_task,
)

# === Tests for _add_prettier_ignore_before_tags ===


def test_add_prettier_ignore_with_trailing_blank_lines() -> None:
    """Test that trailing blank lines don't prevent finding the tag block."""
    description = "Fix bug\n\nBUG=12345\nR=startblock\n\n"
    result = _add_prettier_ignore_before_tags(description)
    assert result == "Fix bug\n\n<!-- prettier-ignore -->\nBUG=12345\nR=startblock\n\n"


# === Tests for _strip_prettier_ignore ===


# === Tests for _fetch_cl_description ===


@patch("sase.ace.handlers.reword.get_vcs_provider")
@patch("sase.running_field.get_workspace_directory")
def test_fetch_cl_description_success(
    mock_get_ws: MagicMock, mock_get_provider: MagicMock
) -> None:
    """Test successful description fetch."""
    mock_get_ws.return_value = "/workspace"
    mock_provider = MagicMock()
    mock_provider.get_description.return_value = (True, "My CL description\n")
    mock_provider.resolve_revision.side_effect = lambda name, *_: name
    mock_get_provider.return_value = mock_provider
    console = MagicMock()

    result = _fetch_cl_description("project", "cl/123", console)

    assert result == "My CL description\n"
    mock_provider.get_description.assert_called_once_with("cl/123", "/workspace")


@patch("sase.running_field.get_workspace_directory")
def test_fetch_cl_description_workspace_error(
    mock_get_ws: MagicMock,
) -> None:
    """Test returns None when workspace lookup fails."""
    mock_get_ws.side_effect = RuntimeError("no workspace")
    console = MagicMock()

    result = _fetch_cl_description("project", "cl/123", console)

    assert result is None


@patch("sase.ace.handlers.reword.get_vcs_provider")
@patch("sase.running_field.get_workspace_directory")
def test_fetch_cl_description_cl_desc_fails(
    mock_get_ws: MagicMock, mock_get_provider: MagicMock
) -> None:
    """Test returns None when cl_desc command fails."""
    mock_get_ws.return_value = "/workspace"
    mock_provider = MagicMock()
    mock_provider.get_description.return_value = (False, "cl_desc failed")
    mock_get_provider.return_value = mock_provider
    console = MagicMock()

    result = _fetch_cl_description("project", "cl/123", console)

    assert result is None


# === Tests for _open_editor_with_content ===


@patch("sase.ace.handlers.reword.get_editor", return_value="false")
@patch("sase.ace.handlers.reword.subprocess.run")
def test_open_editor_with_content_editor_fails(
    mock_run: MagicMock, _mock_editor: MagicMock
) -> None:
    """Test returns None when editor exits non-zero."""
    mock_run.return_value = MagicMock(returncode=1)
    console = MagicMock()

    result = _open_editor_with_content("hello", console)

    assert result is None


@patch("sase.ace.handlers.reword.get_editor", return_value="cat")
@patch("sase.ace.handlers.reword.subprocess.run")
def test_open_editor_with_content_cleans_up_temp_file(
    mock_run: MagicMock, _mock_editor: MagicMock
) -> None:
    """Test that temp file is cleaned up after editor."""
    temp_paths: list[str] = []

    def capture_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if len(cmd) == 2:
            temp_paths.append(cmd[1])
        return MagicMock(returncode=0)

    mock_run.side_effect = capture_run
    console = MagicMock()

    _open_editor_with_content("test content", console)

    assert len(temp_paths) == 1
    assert not os.path.exists(temp_paths[0])


# === Tests for handle_reword_prepare ===


def _make_context_and_changespec(
    status: str = "Draft", cl: str | None = "123456"
) -> tuple[MagicMock, MagicMock]:
    """Create mock WorkflowContext and ChangeSpec."""
    ctx = MagicMock()
    ctx.console = MagicMock()

    cs = MagicMock()
    cs.status = status
    cs.cl = cl
    cs.name = "cl/test"
    cs.project_basename = "project"
    cs.file_path = "/path/to/project.gp"

    return ctx, cs


@patch("sase.ace.handlers.reword._open_editor_with_content", return_value=None)
@patch(
    "sase.ace.handlers.reword._fetch_cl_description",
    return_value="Original desc\n",
)
def test_handle_reword_prepare_editor_returns_none(
    _mock_fetch: MagicMock, _mock_editor: MagicMock
) -> None:
    """Test prepare returns None when editor returns None."""
    ctx, cs = _make_context_and_changespec()

    result = handle_reword_prepare(ctx, cs)

    assert result is None
    assert "cancelled" in ctx.console.print.call_args[0][0].lower()


@patch("sase.ace.handlers.reword._open_editor_with_content")
@patch("sase.ace.handlers.reword._fetch_cl_description")
def test_handle_reword_prepare_trailing_newline_no_false_diff(
    mock_fetch: MagicMock, mock_editor: MagicMock
) -> None:
    """Test trailing newline differences don't trigger a reword."""
    mock_fetch.return_value = "Same description\n"
    mock_editor.return_value = "Same description"  # no trailing newline
    ctx, cs = _make_context_and_changespec(status="Ready")

    result = handle_reword_prepare(ctx, cs)

    assert result is None


@patch("sase.ace.handlers.reword._fetch_cl_description", return_value=None)
def test_handle_reword_prepare_fetch_fails(
    _mock_fetch: MagicMock,
) -> None:
    """Test prepare returns None when description fetch fails."""
    ctx, cs = _make_context_and_changespec()

    result = handle_reword_prepare(ctx, cs)

    assert result is None


@patch(
    "sase.ace.handlers.reword._open_editor_with_content",
    return_value="New description\n",
)
@patch(
    "sase.ace.handlers.reword._fetch_cl_description",
    return_value="Old description\n",
)
def test_handle_reword_prepare_returns_edited_description(
    _mock_fetch: MagicMock, _mock_editor: MagicMock
) -> None:
    """Test prepare returns edited description when changed."""
    ctx, cs = _make_context_and_changespec()

    result = handle_reword_prepare(ctx, cs)

    assert result == "New description\n"


# === Tests for reword_execute_task ===


@patch("sase.ace.handlers.reword._sync_description_bg")
@patch("sase.ace.handlers.reword.get_vcs_provider")
@patch("sase.ace.handlers.reword.run_sase_hg_clean", return_value=(True, None))
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws", "fig_101"),
)
@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.running_field.get_first_available_axe_workspace", return_value=101)
@patch("sase.running_field.release_workspace")
def test_reword_execute_task_full_flow(
    mock_release: MagicMock,
    _mock_first_ws: MagicMock,
    mock_claim: MagicMock,
    _mock_get_ws_dir: MagicMock,
    _mock_clean: MagicMock,
    mock_get_provider: MagicMock,
    mock_sync: MagicMock,
) -> None:
    """Test full reword execute task flow."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.reword.return_value = (True, None)
    mock_provider.prepare_description_for_reword.side_effect = lambda d: d
    mock_get_provider.return_value = mock_provider

    success, message = reword_execute_task(
        "cl/test", "/path/to/project.gp", "project", "New description\n"
    )

    assert success is True
    assert "cl/test" in message
    mock_claim.assert_called_once()
    mock_provider.prepare_description_for_reword.assert_called_once_with(
        "New description\n"
    )
    mock_provider.reword.assert_called_once_with("New description\n", "/ws")
    mock_sync.assert_called_once_with("/ws", "/path/to/project.gp", "cl/test")
    mock_release.assert_called_once()


@patch("sase.ace.handlers.reword.get_vcs_provider")
@patch("sase.ace.handlers.reword.run_sase_hg_clean", return_value=(True, None))
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws", "fig_101"),
)
@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.running_field.get_first_available_axe_workspace", return_value=101)
@patch("sase.running_field.release_workspace")
def test_reword_execute_task_checkout_fails(
    mock_release: MagicMock,
    _mock_first_ws: MagicMock,
    _mock_claim: MagicMock,
    _mock_get_ws_dir: MagicMock,
    _mock_clean: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test execute task returns failure when checkout fails."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "branch not found")
    mock_get_provider.return_value = mock_provider

    success, message = reword_execute_task(
        "cl/test", "/path/to/project.gp", "project", "New description\n"
    )

    assert success is False
    assert "checkout failed" in message
    mock_release.assert_called_once()


@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws", "fig_101"),
)
@patch("sase.running_field.claim_workspace", return_value=False)
@patch("sase.running_field.get_first_available_axe_workspace", return_value=101)
def test_reword_execute_task_workspace_claim_fails(
    _mock_first_ws: MagicMock,
    _mock_claim: MagicMock,
    _mock_get_ws_dir: MagicMock,
) -> None:
    """Test execute task returns failure when workspace claim fails."""
    success, message = reword_execute_task(
        "cl/test", "/path/to/project.gp", "project", "New description\n"
    )

    assert success is False
    assert "Failed to claim" in message
