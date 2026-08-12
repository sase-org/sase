"""Tests for the global Patch runner counters.

``count_all_runners_global`` is called per tick by runner-pool admission
control, some of it while the shared counter's exclusive lock is held, so it
must load the ProjectSpec archive once through the cached snapshot rather than
parsing it twice.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.patch import validation


def _status_line(suffix_type: str) -> SimpleNamespace:
    return SimpleNamespace(suffix_type=suffix_type)


def _patch(
    *,
    hooks: list[Any] | None = None,
    comments: list[Any] | None = None,
    mentors: list[Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        hooks=hooks or [], comments=comments or [], mentors=mentors or []
    )


def _archive() -> list[SimpleNamespace]:
    """Two hook runners and three agent runners across three Patches."""
    return [
        _patch(
            hooks=[
                SimpleNamespace(
                    is_unlimited=False,
                    status_lines=[
                        _status_line("running_process"),
                        _status_line("running_agent"),
                    ],
                ),
                # Unlimited hooks never count toward the hook-runner limit.
                SimpleNamespace(
                    is_unlimited=True,
                    status_lines=[_status_line("running_process")],
                ),
            ]
        ),
        _patch(
            hooks=[
                SimpleNamespace(
                    is_unlimited=False,
                    status_lines=[_status_line("running_process")],
                )
            ],
            comments=[_status_line("running_agent")],
        ),
        _patch(
            mentors=[SimpleNamespace(status_lines=[_status_line("running_agent")])],
        ),
    ]


@pytest.fixture
def counted_loads(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count cached vs uncached archive loads made by the counters."""
    calls = {"cached": 0, "uncached": 0}

    def fake_cached(*_args: object, **_kwargs: object) -> list[SimpleNamespace]:
        calls["cached"] += 1
        return _archive()

    def fake_uncached(*_args: object, **_kwargs: object) -> list[SimpleNamespace]:
        calls["uncached"] += 1
        return _archive()

    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached", fake_cached, raising=True
    )
    monkeypatch.setattr("sase.ace.patch.find_all_patches", fake_uncached, raising=True)
    return calls


def test_count_all_runners_global_loads_the_archive_once(
    counted_loads: dict[str, int],
) -> None:
    """One shared cached load backs both counts, with no uncached parse."""
    total = validation.count_all_runners_global()

    assert total == 5
    assert counted_loads["cached"] == 1
    assert counted_loads["uncached"] == 0


def test_count_all_runners_global_matches_the_separate_counters(
    counted_loads: dict[str, int],
) -> None:
    """Switching to the shared snapshot preserved the arithmetic."""
    total = validation.count_all_runners_global()
    separate = (
        validation.count_hook_runners_global() + validation.count_agent_runners_global()
    )

    assert total == separate
    # The old implementation was exactly the `separate` expression: two
    # uncached full-archive parses per call instead of one cached load.
    assert counted_loads == {"cached": 1, "uncached": 2}


def test_count_hook_and_agent_runners_global_splits_the_shared_load(
    counted_loads: dict[str, int],
) -> None:
    """The shared helper returns hook and agent counts from one load."""
    hook_runners, agent_runners = validation.count_hook_and_agent_runners_global()

    assert (hook_runners, agent_runners) == (2, 3)
    assert counted_loads["cached"] == 1
