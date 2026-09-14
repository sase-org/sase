"""Command/cwd rendering tests for :func:`sase.monitor.followup_prompt.compose_followup_prompt`."""

from __future__ import annotations

from sase.monitor.followup_prompt import compose_followup_prompt
from sase.monitor.result_projection import build_monitor_result_wire
from sase.xprompt._literal_zones import code_literal_ranges
from sase.xprompt.directives import extract_prompt_directives

from ._followup_prompt_fixtures import _COMMON


def test_compose_followup_prompt_accepts_long_env_command() -> None:
    common = dict(_COMMON)
    common["command"] = "SASE_CORE_WHEEL=/tmp/" + ("x" * 1_100) + " just check"

    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=42.0,
        timeout_seconds=2700.0,
        **common,
    )

    assert "FAILED — exit 1" in prompt
    assert common["command"] in prompt


def test_monitor_result_wire_preserves_complete_long_command_identity() -> None:
    command = "SASE_CORE_WHEEL=/tmp/" + ("x" * 2_000) + " just check"

    result = build_monitor_result_wire(
        monitor_id="m4kqm4kqm4kq",
        monitor_state="failed",
        exit_code=1,
        command=command,
        cwd="/home/bryan/work/acme",
        started_at="2026-08-12T14:02:11+00:00",
        stopped_at="2026-08-12T14:19:48+00:00",
        elapsed_seconds=42.0,
    )

    assert result["command"] == ["/bin/sh", "-c", command]
    assert "command part omitted" not in str(result["command"])


def test_compose_followup_prompt_command_and_cwd_are_fenced_not_inline_code() -> None:
    common = dict(_COMMON)
    common["command"] = "echo #commit && echo %model:haiku"
    common["cwd"] = "/tmp/x"
    prompt = compose_followup_prompt(
        starter_name=None,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        **common,
    )

    # A single backtick inline code span is not an xprompt literal zone; only
    # fenced code (and disabled regions) are. The command/cwd values must
    # therefore land inside a genuinely-detected fenced block.
    zones = code_literal_ranges(prompt)
    command_start = prompt.index(common["command"])
    command_end = command_start + len(common["command"])
    assert any(start <= command_start and command_end <= end for start, end in zones), (
        "command text must be fully inside a detected literal zone"
    )

    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model is None
    assert "%model:haiku" in cleaned


def test_compose_followup_prompt_accepts_long_shell_command() -> None:
    common = dict(_COMMON)
    common["command"] = "printf start && " + ("printf chunk && " * 90) + "printf done"

    prompt = compose_followup_prompt(
        starter_name=None,
        monitor_state="failed",
        exit_code=143,
        elapsed_seconds=698.0,
        timeout_seconds=2700.0,
        **common,
    )

    assert common["command"] in prompt
    assert "FAILED — exit 143" in prompt
