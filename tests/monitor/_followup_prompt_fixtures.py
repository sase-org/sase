"""Shared fixtures for :func:`sase.monitor.followup_prompt.compose_followup_prompt` tests."""

from __future__ import annotations

from sase.xprompt._disabled_regions import disabled_region_ranges

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


def _assert_inside_any_region(prompt: str, text: str) -> None:
    regions = disabled_region_ranges(prompt)
    start = prompt.index(text)
    end = start + len(text)
    assert any(
        region_start <= start and end <= region_end
        for region_start, region_end in regions
    ), f"{text!r} must be inside a disabled region"
