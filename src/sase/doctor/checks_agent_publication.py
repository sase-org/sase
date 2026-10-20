"""Agent publication outbox checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec
from sase.doctor.checks_agent_publication_outbox import (
    check_agent_publication_outbox,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def agent_publication_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default agent-publication check specs."""
    return (
        CheckSpec(
            id="state.agent_publication_outbox",
            group="state",
            title="Agent publication outbox",
            runner=lambda: check_agent_publication_outbox(context),
        ),
    )


__all__ = ["agent_publication_check_specs"]
