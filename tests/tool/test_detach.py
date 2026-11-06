"""Starter-scoped detached-run tests (historic import facade)."""

from __future__ import annotations

# ruff: noqa: F822 -- __all__ entries resolve lazily via __getattr__ below.

import importlib

__all__ = [
    "test_detach_refuses_human_with_handoff_alternative",
    "test_detach_refuses_hand_off_together_verbose_and_tail",
    "test_detach_refuses_inside_live_owner_and_parent_run",
    "test_detach_unresolvable_starter_is_fail_closed",
    "test_detach_accepts_long_tool_skipping_inline_refusal",
    "test_detach_quiet_prints_only_run_id",
    "test_detach_keep_going_travels_in_envelope",
    "test_resolve_starter_reads_runner_meta_and_alive_needs_identity",
    "test_starter_alive_sees_through_unreaped_zombies",
    "test_cleanup_stops_only_matching_unjoined_runs",
    "test_cleanup_preserves_run_with_staged_join_reservation",
    "test_cleanup_never_raises_without_agent_context",
    "test_watchdog_stops_unjoined_run_when_starter_dies",
    "test_watchdog_reports_ended_join_monitor",
    "test_watchdog_preserves_run_joined_to_active_monitor",
    "test_watchdog_preserves_run_with_staged_join_reservation",
    "test_detached_runs_raise_no_settlement_notification",
    "test_show_renders_starter_and_join",
    "test_parser_detach_mutually_exclusive_with_hand_off",
    "test_detached_owner_tags_carry_detached_marker",
    "test_join_tags_carry_only_the_join_prefix",
]

_LAZY_SUBMODULES = (
    ".test_detach_execution",
    ".test_detach_liveness",
    ".test_detach_watchdog",
    ".test_detach_surfaces",
)


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    for submodule in _LAZY_SUBMODULES:
        module = importlib.import_module(submodule, __package__)
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
