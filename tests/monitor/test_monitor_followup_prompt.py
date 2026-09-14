"""Golden tests for :func:`sase.monitor.followup_prompt.compose_followup_prompt`.

Covers the outcome banner: fork prefix, exit-code/timeout wording, and the
fork-prefix omission when the starter never settled. See the sibling
``test_monitor_followup_prompt_*`` modules for diagnostics, command/cwd
rendering, output-tail rendering, routing directives, and adversarial-input
safety.
"""

from __future__ import annotations

from sase.monitor.followup_prompt import compose_followup_prompt

from ._followup_prompt_fixtures import _COMMON


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
    assert "```text\njust check-full\n```" in prompt
    assert "sase monitor show m4kqm4kqm4kq --all-lines" in prompt
    assert _COMMON["next_action"] in prompt
    assert prompt.rstrip().endswith("%xprompts_enabled:true")


def test_compose_followup_prompt_default_auto_completed_omits_raw_tail() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=97.0,
        timeout_seconds=2700.0,
        **_COMMON,
    )

    assert "## Last" not in prompt
    assert "line 1" not in prompt
    assert "raw output omitted: `facts_only`" in prompt


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


def test_compose_followup_prompt_idle_timeout_names_the_idle_budget() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="timeout",
        exit_code=None,
        elapsed_seconds=620.0,
        timeout_seconds=2700.0,
        idle_timeout_seconds=600.0,
        timeout_kind="idle",
        **_COMMON,
    )

    assert "TIMED OUT — no output for 10m 0s" in prompt


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
    assert prompt.startswith("%xprompts_enabled:false\n")
    assert "# Monitored command finished" in prompt
