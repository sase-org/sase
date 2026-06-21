"""AgyProvider print-mode no-progress detection and continuation tests."""

import os
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.agy import AgyProvider, _looks_like_no_progress
from sase.llm_provider.types import LLMInvocationError


def test_agy_no_progress_text_detection_positive_fixtures() -> None:
    agy_022_stub = textwrap.dedent(
        """\
        I will inspect the first plan file.
        I will inspect the second plan file.
        I will compare the implementation risks.
        I will pause to wait for the command output to complete.
        """
    )
    agy_03b_stub = textwrap.dedent(
        """\
        I will list chats matching `038.cdx`.
        I will open the matching transcript.
        I will stop calling tools for a moment and wait for the background
        search command to finish and notify me with its output.
        """
    )

    assert _looks_like_no_progress(agy_022_stub) is True
    assert _looks_like_no_progress(agy_03b_stub) is True
    assert _looks_like_no_progress("  \n\t") is True


def test_agy_no_progress_text_detection_negative_fixtures() -> None:
    completed_recommendation = textwrap.dedent(
        """\
        Recommendation: choose `036.cdx`.

        It covers the provider-local recovery loop, documents the print-mode
        background-task hazard, and keeps the runner/finalizer unchanged.
        """
    )
    completed_implementation = textwrap.dedent(
        """\
        Implemented the provider-local guard in `agy.py`.

        Tests: passed for the focused provider suite. The final behavior now
        returns a direct answer instead of a waiting stub.
        """
    )

    assert _looks_like_no_progress(completed_recommendation) is False
    assert _looks_like_no_progress(completed_implementation) is False


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_continues_once_after_planning_only_reply(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    calls = {"n": 0}

    def _stream_side_effect(
        process: object, suppress_output: bool = False, clean_ansi: bool = False
    ) -> tuple[str, str, int]:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                "I will inspect the plans.\n"
                "I will pause to wait for the command output to complete.\n",
                "",
                0,
            )
        return ("Recommendation: use plan B.", "", 0)

    mock_stream.side_effect = _stream_side_effect

    result = AgyProvider().invoke(
        "review two plans", model_tier="large", suppress_output=True
    )

    assert calls["n"] == 2
    second_prompt = mock_popen.call_args_list[1].args[0][-1]
    assert "review two plans" in second_prompt
    assert "--- Work So Far ---" in second_prompt
    assert "I will inspect the plans." in second_prompt
    assert "--- Required Continuation ---" in second_prompt
    assert "Run your tools synchronously now" in second_prompt
    assert result.content == "Recommendation: use plan B."


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_clean_answer_does_not_continue(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("Recommendation: use plan A.", "", 0)

    result = AgyProvider().invoke(
        "review two plans", model_tier="large", suppress_output=True
    )

    assert mock_stream.call_count == 1
    assert mock_popen.call_count == 1
    assert result.content == "Recommendation: use plan A."


@patch.dict(os.environ, {"SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS": "1"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_no_progress_cap_exhaustion_raises(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = (
        "I will inspect the plans.\n"
        "I will wait for the background command to notify me.\n",
        "",
        0,
    )

    with pytest.raises(LLMInvocationError) as exc_info:
        AgyProvider().invoke(
            "review two plans", model_tier="large", suppress_output=True
        )

    assert mock_stream.call_count == 2
    assert mock_popen.call_count == 2
    message = str(exc_info.value)
    assert "no-progress print-mode reply" in message
    assert "planning_only_text" in message
