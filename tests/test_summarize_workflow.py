"""Tests for summarize_utils module (summarize via execute_workflow + #json)."""

from unittest.mock import MagicMock, patch

from sase.summarize_utils import get_file_summary


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_returns_summary_on_success(
    mock_execute: MagicMock,
) -> None:
    """Test that get_file_summary returns the summary on success."""
    mock_result = MagicMock()
    mock_result.response_text = '{"summary": "Fixed config typo"}'
    mock_execute.return_value = mock_result

    result = get_file_summary(
        target_file="/path/to/file.txt",
        usage="a test",
        fallback="Fallback text",
    )
    assert result == "Fixed config typo"
    mock_execute.assert_called_once_with(
        "summarize",
        positional_args=[],
        named_args={"target_file": "/path/to/file.txt", "usage": "a test"},
        artifacts_dir=None,
        silent=True,
    )


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_fallback_on_exception(
    mock_execute: MagicMock,
) -> None:
    """Test that get_file_summary returns fallback when workflow fails."""
    mock_execute.side_effect = Exception("Test error")

    result = get_file_summary(
        target_file="/nonexistent/file.txt",
        usage="a test",
        fallback="Fallback text",
    )
    assert result == "Fallback text"


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_default_fallback(mock_execute: MagicMock) -> None:
    """Test that get_file_summary uses default fallback."""
    mock_result = MagicMock()
    mock_result.response_text = None
    mock_execute.return_value = mock_result

    result = get_file_summary(
        target_file="/path/to/file.txt",
        usage="a test",
    )
    assert result == "Operation completed"


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_with_code_fenced_json(
    mock_execute: MagicMock,
) -> None:
    """Test that get_file_summary handles code-fenced JSON responses."""
    mock_result = MagicMock()
    mock_result.response_text = '```json\n{"summary": "Added timeout config"}\n```'
    mock_execute.return_value = mock_result

    result = get_file_summary(
        target_file="/path/to/file.txt",
        usage="a test",
    )
    assert result == "Added timeout config"


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_passes_artifacts_dir(
    mock_execute: MagicMock,
) -> None:
    """Test that artifacts_dir is passed through to execute_workflow."""
    mock_result = MagicMock()
    mock_result.response_text = '{"summary": "Test summary"}'
    mock_execute.return_value = mock_result

    get_file_summary(
        target_file="/path/to/file.txt",
        usage="a test",
        artifacts_dir="/tmp/artifacts",
    )
    mock_execute.assert_called_once_with(
        "summarize",
        positional_args=[],
        named_args={"target_file": "/path/to/file.txt", "usage": "a test"},
        artifacts_dir="/tmp/artifacts",
        silent=True,
    )


@patch("sase.summarize_utils.execute_workflow")
def test_get_file_summary_fallback_on_empty_summary(
    mock_execute: MagicMock,
) -> None:
    """Test fallback when JSON has empty summary."""
    mock_result = MagicMock()
    mock_result.response_text = '{"summary": ""}'
    mock_execute.return_value = mock_result

    result = get_file_summary(
        target_file="/path/to/file.txt",
        usage="a test",
    )
    assert result == "Operation completed"
