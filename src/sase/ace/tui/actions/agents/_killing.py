"""Agent killing methods for the ace TUI app.

This module remains the public import and compatibility surface for agent
killing. Implementation lives in focused mixins so individual files stay small,
while existing tests and callers can still patch private helpers here.
"""

from __future__ import annotations

import os as os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import Patch unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures).
from ....patch import Patch

from ._dismissing import AgentDismissingMixin
from ._kill_all_actions import AgentKillAllActionsMixin
from ._kill_cleanup_planning import (
    plan_bulk_kill_cleanup_side_effects as _plan_bulk_kill_cleanup_side_effects,
)
from ._kill_cleanup_planning import (
    plan_single_agent_kill_cleanup as _plan_single_agent_kill_cleanup,
)
from ._kill_flow import AgentKillFlowMixin
from ._kill_identity import AgentKillIdentityMixin
from ._kill_persistence import AgentIdentity as AgentIdentity
from ._kill_persistence import BulkKillItem as BulkKillItem
from ._kill_persistence import KillKind as KillKind
from ._kill_persistence import (
    persist_bulk_kill_side_effects as persist_bulk_kill_side_effects,
)
from ._kill_persistence import persist_kill_side_effects as persist_kill_side_effects
from ._kill_processes import AgentKillProcessMixin
from ._kill_procs import AgentKillPersistenceProcMixin
from ._kill_transactions import bulk_kill_summary as _bulk_kill_summary
from ._kill_transactions import (
    bulk_kill_task_display_name as _bulk_kill_task_display_name,
)
from ._kill_transactions import (
    persist_bulk_kill_transaction as _persist_bulk_kill_transaction,
)
from ._kill_transactions import (
    persist_single_kill_transaction as _persist_single_kill_transaction,
)

# Re-export for backwards compatibility (_loading.py imports this, tests patch it).
from ._killing_utils import delete_agent_artifacts as delete_agent_artifacts
from ._killing_utils import (
    dismiss_notifications_for_agents as dismiss_notifications_for_agents,
)
from sase.agent.user_kill import request_user_kill as request_user_kill
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index as sync_dismissed_agent_artifact_index,
)


class AgentKillingMixin(
    AgentKillFlowMixin,
    AgentKillAllActionsMixin,
    AgentKillIdentityMixin,
    AgentKillPersistenceProcMixin,
    AgentKillProcessMixin,
    AgentDismissingMixin,
):
    """Mixin providing agent killing methods.

    Inherits dismissal methods from AgentDismissingMixin. Type hints below
    declare attributes that are defined at runtime by AceApp.
    """

    # Patch state
    patches: list[Patch]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _kill_persistence_inflight: set[tuple[AgentType, str, str | None]]
