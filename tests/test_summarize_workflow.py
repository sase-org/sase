"""Tests for summarize_workflow module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.summarize_utils import get_file_summary
from sase.summarize_workflow import (
    SummarizeWorkflow,
    _extract_summary,
)


# Tests for _build_summarize_prompt
# Tests for _extract_summary
def test_extract_summary_with_summary_prefix() -> None:
    """Test extracting summary with 'Summary:' prefix."""
    result = _extract_summary("Summary: Fixed typo in config file")
    assert result == "Fixed typo in config file"


def test_extract_summary_strips_reasoning_preamble() -> None:
    """Test stripping LLM reasoning sentences like 'I will read...'."""
    result = _extract_summary(
        "I will read the specified file to generate a concise summary of the "
        "proposed changes. I will read the contents of the proposed response "
        "file using a shell command to circumvent the workspace restrictions. "
        "Removed prohibited `ActivityController` from "
        "`competing_deals_data_provider.dart`, updating related tests and "
        "BUILD dependencies to fix presubmit errors."
    )
    assert result.startswith("Removed prohibited")
    assert "I will read" not in result


def test_extract_summary_strips_let_me_preamble() -> None:
    """Test stripping 'Let me...' reasoning preamble."""
    result = _extract_summary(
        "Let me summarize the changes. Added new config option for timeouts."
    )
    assert result == "Added new config option for timeouts."
    assert "Let me" not in result


def test_extract_summary_preserves_single_sentence() -> None:
    """Test that a single sentence starting with 'I will' is NOT stripped."""
    result = _extract_summary("I will not be stripped since I am alone.")
    assert result == "I will not be stripped since I am alone."


def test_extract_summary_with_quotes() -> None:
    """Test extracting summary wrapped in double quotes."""
    result = _extract_summary('"Fixed typo in config file"')
    assert result == "Fixed typo in config file"


def test_extract_summary_with_single_quotes() -> None:
    """Test extracting summary wrapped in single quotes."""
    result = _extract_summary("'Fixed typo in config file'")
    assert result == "Fixed typo in config file"


# Tests for SummarizeWorkflow class
def test_workflow_name() -> None:
    """Test workflow name property."""
    workflow = SummarizeWorkflow("/path/to/file.txt", "a COMMITS entry header")
    assert workflow.name == "summarize"


def test_workflow_description() -> None:
    """Test workflow description property."""
    workflow = SummarizeWorkflow("/path/to/file.txt", "a COMMITS entry header")
    assert "30 words" in workflow.description.lower()


# Tests for get_file_summary utility function
def test_get_file_summary_fallback_on_exception() -> None:
    """Test that get_file_summary returns fallback when workflow fails."""
    with patch("sase.summarize_utils.SummarizeWorkflow") as mock_workflow_class:
        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = Exception("Test error")
        mock_workflow_class.return_value = mock_workflow

        result = get_file_summary(
            target_file="/nonexistent/file.txt",
            usage="a test",
            fallback="Fallback text",
        )
        assert result == "Fallback text"


def test_get_file_summary_returns_summary_on_success() -> None:
    """Test that get_file_summary returns the summary on success."""
    with patch("sase.summarize_utils.SummarizeWorkflow") as mock_workflow_class:
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = True
        mock_workflow.summary = "Fixed config typo"
        mock_workflow_class.return_value = mock_workflow

        result = get_file_summary(
            target_file="/path/to/file.txt",
            usage="a test",
            fallback="Fallback text",
        )
        assert result == "Fixed config typo"


def test_get_file_summary_default_fallback() -> None:
    """Test that get_file_summary uses default fallback."""
    with patch("sase.summarize_utils.SummarizeWorkflow") as mock_workflow_class:
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = False
        mock_workflow.summary = None
        mock_workflow_class.return_value = mock_workflow

        result = get_file_summary(
            target_file="/path/to/file.txt",
            usage="a test",
        )
        assert result == "Operation completed"


# Additional edge case tests
# Tests for SummarizeWorkflow.run() method
@patch("sase.summarize_workflow.invoke_agent")
def test_workflow_run_success(mock_invoke: MagicMock, tmp_path: Path) -> None:
    """Test successful workflow run."""
    test_file = tmp_path / "file.txt"
    test_file.write_text("test content")

    mock_response = MagicMock()
    mock_response.content = "Fixed typo in config"
    mock_invoke.return_value = mock_response

    workflow = SummarizeWorkflow(str(test_file), "a COMMITS entry header")
    result = workflow.run()

    assert result is True
    assert workflow.summary == "Fixed typo in config"
    mock_invoke.assert_called_once()


# Tests for main() function
@patch("sase.summarize_workflow.SummarizeWorkflow")
@patch("sys.argv", ["summarize_workflow.py", "/path/to/file.txt", "a COMMITS header"])
def test_main_success(mock_workflow_class: MagicMock) -> None:
    """Test main() with successful workflow."""
    mock_workflow = MagicMock()
    mock_workflow.run.return_value = True
    mock_workflow.summary = "Fixed typo"
    mock_workflow_class.return_value = mock_workflow

    import pytest
    from sase.summarize_workflow import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0


@patch("sase.summarize_workflow.SummarizeWorkflow")
@patch("sys.argv", ["summarize_workflow.py", "/path/to/file.txt", "a test"])
def test_main_failure(mock_workflow_class: MagicMock) -> None:
    """Test main() with failed workflow."""
    mock_workflow = MagicMock()
    mock_workflow.run.return_value = False
    mock_workflow.summary = None
    mock_workflow_class.return_value = mock_workflow

    import pytest
    from sase.summarize_workflow import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


@patch("sys.argv", ["summarize_workflow.py", "/path/to/file.txt"])
def test_main_missing_usage_arg() -> None:
    """Test main() with missing usage argument."""
    import pytest
    from sase.summarize_workflow import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
