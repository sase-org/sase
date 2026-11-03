"""Public shutdown and completion helpers for ``run_agent_runner``."""

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import add_dismissed_agents
from sase.axe._run_agent_runner_shutdown_finalize import finalize_runner_shutdown
from sase.axe._run_agent_runner_shutdown_types import (
    RunnerShutdownContext,
    RunnerShutdownDeps,
    RunnerShutdownState,
)


def auto_dismiss_completed_agent(cl_name: str, artifacts_timestamp: str) -> None:
    """Persist auto-dismiss identities for a completed background run."""
    try:
        # Dismiss both RUNNING and WORKFLOW identities -- dedup may pick
        # either depending on whether workflow_state.json exists.
        identities = {
            (AgentType.RUNNING, cl_name, artifacts_timestamp),
            (AgentType.WORKFLOW, cl_name, artifacts_timestamp),
        }
        # Merge under the index lock: the TUI and other runners write it too.
        dismissed = add_dismissed_agents(identities)
        sync_dismissed_agent_artifact_index(dismissed, added=identities)
    except Exception:
        pass  # Best effort
