"""Pre-spawn policy guards for CWD-based agent launches."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

# Logger keeps the pre-split module name so existing log filters and the
# guard-failure test keep matching after the split.
log = logging.getLogger("sase.agent.launch_cwd_agents")


def guard_project_tags_for_launch_units(
    submitted_query: str,
    *,
    expanded_segments: Sequence[str],
    record_failed_launch_prompt: Callable[[str], None],
) -> None:
    """Enforce D3 tag policy for each post-fan-out launch unit.

    Runs after swarm/alt fan-out and before any spawn, so an anchored check
    here also covers ``%{+ssae | +sase}`` branches. Fast path: segments
    without ``+`` are skipped without touching the catalog.
    """

    if not any("+" in segment for segment in expanded_segments):
        return
    try:
        from sase.project_tags import (
            ProjectTagError,
            validate_project_tags_for_launch,
        )
    except ImportError:
        return
    for segment in expanded_segments:
        if "+" not in segment:
            continue
        try:
            validate_project_tags_for_launch(segment)
        except ProjectTagError:
            record_failed_launch_prompt(submitted_query)
            raise
        except Exception:  # noqa: BLE001 - cold catalog fails open here.
            continue


def guard_typed_directives_require_admission(
    submitted_query: str,
    expanded_segments: Sequence[str],
    *,
    record_failed_launch_prompt: Callable[[str], None],
) -> None:
    """Fail closed if enabled ``%if`` / ``%proc`` reaches agent-only execution."""
    from sase.agent.launch_request_types import TypedAdmissionRequiredError
    from sase.xprompt.code_value import typed_launch_units_enabled
    from sase.xprompt.directives import has_typed_launch_directive

    if not typed_launch_units_enabled():
        return
    if not any(
        has_typed_launch_directive(segment)
        for segment in (submitted_query, *expanded_segments)
    ):
        return
    record_failed_launch_prompt(submitted_query)
    raise TypedAdmissionRequiredError(
        "typed_launch_units is enabled and this prompt contains an active "
        "%if or %proc directive; it must go through typed admission instead "
        "of the agent-only launch path"
    )


def guard_hard_disabled_launch_units(
    submitted_query: str,
    *,
    expanded_segments: Sequence[str],
    template_groups: Sequence[str | None],
    swarm_xprompts: Sequence[tuple[str, ...]],
    record_failed_launch_prompt: Callable[[str], None],
) -> None:
    """Refuse a confirmed hard-disable block; fail open on guard surprises."""
    from sase.agent.launch_guard import (
        DisabledProviderLaunchError,
        LaunchUnitInput,
        guard_launch_units,
    )

    unit_inputs = tuple(
        LaunchUnitInput(
            prompt=segment,
            template_group=group,
            swarm_xprompts=tuple(swarm),
        )
        for segment, group, swarm in zip(
            expanded_segments,
            template_groups,
            swarm_xprompts,
            strict=True,
        )
    )
    try:
        guard_launch_units(submitted_query, units=unit_inputs)
    except DisabledProviderLaunchError:
        record_failed_launch_prompt(submitted_query)
        raise
    except Exception:
        log.warning(
            "provider-disable launch guard failed open; continuing with launch",
            exc_info=True,
        )
