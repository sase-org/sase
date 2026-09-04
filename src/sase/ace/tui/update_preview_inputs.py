"""Off-pane collection of inputs for a scoped comprehensive-update preview."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    error_text,
)
from sase.ace.tui.modals.plugins_browser_loading import probe_uv_tool
from sase.ace.update_scope import UpdateLeg
from sase.agent_clis.models import AgentCliStatus
from sase.agent_clis.operations import collect_agent_cli_statuses
from sase.updates import UpdateStatus


@dataclass(frozen=True)
class UpdatePreviewInputs:
    """Explicit inputs for :func:`build_comprehensive_update_preview`."""

    uv_tool: object | None
    agent_cli_statuses: tuple[AgentCliStatus, ...]
    agent_cli_error: str | None
    offline: bool
    cached_status: UpdateStatus | None


def collect_update_preview_inputs(
    *,
    cached_status: UpdateStatus | None,
    legs: Collection[UpdateLeg],
) -> UpdatePreviewInputs:
    """Collect the minimum live inputs the selected legs require.

    Runs off-thread. Skipping a leg's collection is what keeps a Providers-only
    or SASE-only selection quick.
    """
    uv_tool: object | None = None
    agent_cli_statuses: tuple[AgentCliStatus, ...] = ()
    agent_cli_error: str | None = None
    selected = frozenset(legs)
    if UpdateLeg.SASE in selected:
        uv_tool = probe_uv_tool()
    if UpdateLeg.PROVIDERS in selected:
        try:
            agent_cli_statuses = collect_agent_cli_statuses(
                refresh=False, offline=False
            )
        except Exception as exc:  # noqa: BLE001 - keep other legs plannable.
            agent_cli_error = error_text(exc)
    return UpdatePreviewInputs(
        uv_tool=uv_tool,
        agent_cli_statuses=agent_cli_statuses,
        agent_cli_error=agent_cli_error,
        offline=False,
        cached_status=cached_status,
    )


__all__ = ["UpdatePreviewInputs", "collect_update_preview_inputs"]
