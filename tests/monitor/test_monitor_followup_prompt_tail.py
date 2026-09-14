"""Output-tail rendering tests for :func:`sase.monitor.followup_prompt.compose_followup_prompt`."""

from __future__ import annotations

from sase.monitor.followup_prompt import compose_followup_prompt
from sase.monitor.result_projection import TOTAL_RAW_EXCERPT_MAX_BYTES

from ._followup_prompt_fixtures import _COMMON, _assert_inside_any_region


def test_compose_followup_prompt_widens_the_fence_around_backticks_in_output() -> None:
    common = dict(_COMMON)
    common["output_text"] = "normal line\n``` a fenced-looking line\nmore output\n"
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        next_output="tail",
        **common,
    )

    assert "````text" in prompt
    assert prompt.count("````") == 2


def test_compose_followup_prompt_tail_is_limited_to_the_requested_line_count() -> None:
    common = dict(_COMMON)
    common["output_text"] = "\n".join(f"line {i}" for i in range(500)) + "\n"
    common["tail_lines"] = 3
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        next_output="tail",
        **common,
    )

    assert "## Last 3 lines of output" in prompt
    assert "line 497\nline 498\nline 499" in prompt
    assert "line 0\n" not in prompt


def test_compose_followup_prompt_tail_is_limited_to_character_budget() -> None:
    common = dict(_COMMON)
    common["output_text"] = "discard:" + ("x" * TOTAL_RAW_EXCERPT_MAX_BYTES)
    common["tail_lines"] = 1
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        next_output="tail",
        **common,
    )

    assert "Output tail truncated: omitted 8 earlier characters." in prompt
    assert "discard:" not in prompt
    _assert_inside_any_region(prompt, "Output tail truncated")


def test_compose_followup_prompt_next_output_none_omits_the_tail_section() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        next_output="none",
        **_COMMON,
    )

    assert "## Last" not in prompt
    assert "line 1" not in prompt
    assert "sase monitor show m4kqm4kqm4kq --all-lines" in prompt


def test_compose_followup_prompt_next_output_file_points_at_the_log_path() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        next_output="file",
        output_log_path="/home/bryan/.sase/projects/acme/artifacts/live_reply.md",
        **_COMMON,
    )

    assert "## Last" not in prompt
    assert "/home/bryan/.sase/projects/acme/artifacts/live_reply.md" in prompt
    assert "sase monitor show m4kqm4kqm4kq --all-lines" in prompt
