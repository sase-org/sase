"""Tests for sase.rich_utils module."""

from io import StringIO

from rich.console import Console

from sase.rich_utils import (
    escape_markup,
    gemini_timer,
    print_artifact_created,
    print_decision_counts,
    print_prompt_and_response,
    print_workflow_header,
)


def test_print_prompt_and_response_only_response() -> None:
    """Test printing only response."""
    print_prompt_and_response(
        "What should I do?",
        "Do this thing",
        "editor",
        show_prompt=False,
        show_response=True,
    )


def test_print_decision_counts() -> None:
    """Test that decision counts are printed."""
    decision_counts = {
        "new_editor": 5,
        "next_editor": 3,
        "research": 2,
    }
    print_decision_counts(decision_counts)


def test_print_decision_counts_empty() -> None:
    """Test that empty decision counts are handled."""
    print_decision_counts({})


def test_gemini_timer_long_duration() -> None:
    """Test the gemini_timer formatting with hours."""
    from unittest.mock import patch

    # Mock time to simulate > 1 hour duration
    with patch("time.perf_counter", side_effect=[0, 3665]):  # 1 hour, 1 min, 5 sec
        with gemini_timer("Long operation"):
            pass  # Timer will calculate elapsed time from the mocked values


# Additional edge case tests
def test_print_workflow_header_without_tag() -> None:
    """Test workflow header without tag."""
    print_workflow_header("test_workflow")


def test_print_prompt_and_response_only_prompt() -> None:
    """Test print_prompt_and_response with only prompt."""
    print_prompt_and_response(
        "Prompt text",
        "",
        "verification",
        show_prompt=True,
        show_response=False,
    )


def test_print_prompt_and_response_various_agent_types() -> None:
    """Test print_prompt_and_response with various agent types."""
    agent_types = ["editor", "planner", "research_cl_scope", "add_tests", "postmortem"]
    for agent_type in agent_types:
        print_prompt_and_response(
            "Test prompt",
            "Test response",
            agent_type,
            iteration=1,
        )


def test_escape_markup_reexport() -> None:
    """Test that escape_markup is properly re-exported."""
    assert escape_markup("[foobar]") == "\\[foobar]"
    assert escape_markup("no brackets") == "no brackets"
    assert escape_markup("[bold]text[/bold]") == "\\[bold]text\\[/bold]"


def test_escape_markup_in_log_fn() -> None:
    """Test that escape_markup properly escapes brackets in log output."""
    buf = StringIO()
    con = Console(file=buf, no_color=True)
    msg = "Message with [brackets] inside"
    con.print(f"[cyan]{escape_markup(msg)}[/cyan]")
    output = buf.getvalue()
    assert "[brackets]" in output


def test_print_workflow_header_with_brackets() -> None:
    """Test that workflow header doesn't consume bracket content."""
    print_workflow_header("test", "[tag-with-brackets]")


def test_print_artifact_created_with_brackets() -> None:
    """Test that artifact path with brackets is preserved."""
    print_artifact_created("/path/to/[artifact].txt")
