"""Tests for sase.output module."""

import threading
import time
from io import StringIO
from unittest.mock import patch

from rich.console import Console
from rich.live import Live

from sase.output import (
    escape_markup,
    provider_timer,
    print_artifact_created,
    print_decision_counts,
    print_prompt_and_response,
    print_workflow_header,
)
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


def _provider_timer_threads(
    existing_ids: set[int | None],
) -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "sase-provider-timer"
        and thread.ident not in existing_ids
        and thread.is_alive()
    ]


def _wait_for_provider_timer_thread(
    existing_ids: set[int | None],
    *,
    timeout: float = LOAD_TOLERANT_TIMEOUT,
) -> threading.Thread:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        threads = _provider_timer_threads(existing_ids)
        if len(threads) == 1:
            return threads[0]
        time.sleep(0.01)  # sase-test-wait: provider timer thread start under soak
    raise AssertionError(
        f"sase-provider-timer never appeared within {timeout}s; "
        f"live={_provider_timer_threads(existing_ids)!r}"
    )


def _wait_until_provider_timer_threads_stop(
    existing_ids: set[int | None],
    *,
    timeout: float = LOAD_TOLERANT_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _provider_timer_threads(existing_ids):
            return
        time.sleep(0.01)  # sase-test-wait: provider timer thread join under soak
    raise AssertionError(
        f"sase-provider-timer still live after {timeout}s; "
        f"live={_provider_timer_threads(existing_ids)!r}"
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


def test_provider_timer_long_duration() -> None:
    """Test the provider_timer formatting with hours."""

    # Mock time to simulate > 1 hour duration
    with patch("time.perf_counter", side_effect=[0, 3665]):  # 1 hour, 1 min, 5 sec
        with provider_timer("Long operation"):
            pass  # Timer will calculate elapsed time from the mocked values


def test_provider_timer_stops_background_thread() -> None:
    """Stops the timer thread when the context exits."""
    existing_thread_ids = {thread.ident for thread in threading.enumerate()}
    timer_thread: threading.Thread | None = None

    with patch("sase.output.time.sleep", return_value=None):
        with provider_timer("Short operation"):
            timer_thread = _wait_for_provider_timer_thread(existing_thread_ids)

    assert timer_thread is not None
    _wait_until_provider_timer_threads_stop(existing_thread_ids)
    assert not timer_thread.is_alive()


def test_provider_timer_thread_survives_live_update_errors() -> None:
    """A Live.update exception must not kill the named timer thread."""
    existing_thread_ids = {thread.ident for thread in threading.enumerate()}
    with (
        patch("sase.output._PROVIDER_TIMER_INTERVAL_SECONDS", 0),
        patch.object(Live, "update", side_effect=RuntimeError("display boom")),
        patch("sase.output.time.sleep", return_value=None),
        provider_timer("Short operation"),
    ):
        timer_thread = _wait_for_provider_timer_thread(existing_thread_ids)
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            assert timer_thread.is_alive()
            time.sleep(0.01)  # sase-test-wait: tight update-error loop stays alive
    _wait_until_provider_timer_threads_stop(existing_thread_ids)


def test_provider_timer_thread_starts_before_live_enter() -> None:
    """The named timer thread exists before Live takes stdout."""
    existing_thread_ids = {thread.ident for thread in threading.enumerate()}
    seen_during_enter: list[threading.Thread] = []
    original_enter = Live.__enter__

    def tracking_enter(self: Live) -> Live:
        seen_during_enter.extend(_provider_timer_threads(existing_thread_ids))
        return original_enter(self)

    with (
        patch.object(Live, "__enter__", tracking_enter),
        patch("sase.output.time.sleep", return_value=None),
        provider_timer("Short operation"),
    ):
        _wait_for_provider_timer_thread(existing_thread_ids)
    _wait_until_provider_timer_threads_stop(existing_thread_ids)
    assert seen_during_enter, "sase-provider-timer must start before Live.__enter__"


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


def test_provider_timer_reusable_across_sequential_cycles() -> None:
    """One timer object survives a second provider cycle."""
    with patch("sase.output.time.sleep", return_value=None):
        timer = provider_timer("Short operation")
        with timer:
            pass
        with timer:
            pass


def test_provider_timer_exception_propagates_and_thread_stops() -> None:
    """An exception inside the block propagates and the timer thread stops."""
    existing_thread_ids = {thread.ident for thread in threading.enumerate()}
    timer = provider_timer("Short operation")
    with patch("sase.output.time.sleep", return_value=None):
        try:
            with timer:
                raise ValueError("boom")
        except ValueError as exc:
            assert str(exc) == "boom"
        else:  # pragma: no cover - the timer must not swallow errors
            raise AssertionError("expected ValueError to propagate")
        _wait_until_provider_timer_threads_stop(existing_thread_ids)


def test_provider_timer_nested_entry_raises() -> None:
    """Entering an active timer object raises RuntimeError."""
    import pytest

    with patch("sase.output.time.sleep", return_value=None):
        timer = provider_timer("Short operation")
        with timer:
            with pytest.raises(RuntimeError, match="already active"):
                with timer:
                    pass  # pragma: no cover - nested entry must raise


def test_print_artifact_created_with_brackets() -> None:
    """Test that artifact path with brackets is preserved."""
    print_artifact_created("/path/to/[artifact].txt")
