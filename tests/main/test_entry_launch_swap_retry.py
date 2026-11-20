"""The CLI entry arms the code-swap retry for launch commands only."""

from __future__ import annotations

import pytest

from sase.main import entry


@pytest.mark.parametrize(
    ("argv", "armed"),
    [
        (["sase", "run", "do work"], True),
        (["sase", "run"], True),
        (["sase", "bead", "work", "sase-1"], True),
        (["sase", "bead", "show", "sase-1"], False),
        (["sase", "ace"], False),
        (["sase"], False),
    ],
)
def test_entry_arms_the_retry_for_launch_commands(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], armed: bool
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launch_swap_retry.arm_code_swap_retry",
        lambda: calls.append("armed"),
    )

    entry._arm_launch_swap_retry(argv)

    assert calls == (["armed"] if armed else [])
