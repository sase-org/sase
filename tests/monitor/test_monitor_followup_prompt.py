"""Golden tests for :func:`sase.monitor.followup_prompt.compose_followup_prompt`."""

from __future__ import annotations

from sase.monitor.followup_prompt import compose_followup_prompt

_COMMON = {
    "command": "just check-full",
    "cwd": "/home/bryan/work/acme",
    "reason": "Verify the refactor before handing back to the user.",
    "started_at": "2026-08-12T14:02:11+00:00",
    "stopped_at": "2026-08-12T14:19:48+00:00",
    "monitor_id": "m4kqm4kqm4kq",
    "output_text": "line 1\nline 2\nline 3\n",
    "tail_lines": 200,
    "total_bytes": 2048,
    "output_truncated": False,
    "next_action": "Fix any failures `just check-full` reported, then reply to the user.",
}


def test_compose_followup_prompt_completed_includes_fork_prefix_and_exit_code() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=97.0,
        timeout_seconds=2700.0,
        **_COMMON,
    )

    assert prompt.startswith("#fork:acme--0\n\n")
    assert "COMPLETED — exit 0" in prompt
    assert "`just check-full`" in prompt
    assert "sase monitor show m4kqm4kqm4kq --all-lines" in prompt
    assert prompt.rstrip().endswith(_COMMON["next_action"])


def test_compose_followup_prompt_failed_reports_the_exit_code() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="failed",
        exit_code=3,
        elapsed_seconds=42.0,
        timeout_seconds=2700.0,
        **_COMMON,
    )

    assert "FAILED — exit 3" in prompt


def test_compose_followup_prompt_timeout_says_it_did_not_finish() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="timeout",
        exit_code=None,
        elapsed_seconds=120.0,
        timeout_seconds=120.0,
        **_COMMON,
    )

    assert "TIMED OUT — did not finish after 2m 0s of a 2m 0s budget" in prompt


def test_compose_followup_prompt_omits_fork_prefix_when_starter_did_not_settle() -> (
    None
):
    prompt = compose_followup_prompt(
        starter_name=None,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=5.0,
        timeout_seconds=0.0,
        **_COMMON,
    )

    assert "#fork:" not in prompt
    assert prompt.startswith("# Monitored command finished")


def test_compose_followup_prompt_widens_the_fence_around_backticks_in_output() -> None:
    common = dict(_COMMON)
    common["output_text"] = "normal line\n``` a fenced-looking line\nmore output\n"
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
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
        **common,
    )

    assert "## Last 3 lines of output" in prompt
    assert "line 497\nline 498\nline 499" in prompt
    assert "line 0\n" not in prompt
