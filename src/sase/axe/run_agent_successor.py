"""In-process agent-session-successor engine for the agent execution loop.

Plan-approval coder hand-off and questions follow-up both become the next
agent-session member with this six-step sequence. The order is load-bearing:

1. Bump ``state.agent_step`` and ``promote_to_workflow`` when the step
   reaches 2 and the agent is named. Promotion turns a lone agent into an
   agent-session root and must happen before follow-up artifacts are created.
2. Resolve the successor suffix: ``request.suffix`` verbatim, otherwise
   ``allocate_agent_session_child_suffix`` on ``request.suffix_template``,
   otherwise an unnamed-agent template render (``fallback_token``).
3. Set ``state.current_role_suffix``, then ``create_followup_artifacts``
   with ``agent_name_override=plan_chain_agent_name(...)``.
4. Write follow-up model metadata when ``request.model`` is set.
5. Set ``state.current_prompt`` to the request prompt.
6. ``store_followup_prompt_artifact`` under ``request.prompt_artifact_label``.

Callers assemble the prompt, relationships, and (for questions) the
promote role-suffix. This module only sequences the hand-off.

Compatibility facade preserving the historical
``sase.axe.run_agent_successor`` import surface. The implementation lives in
smaller focused ``run_agent_successor_*`` modules.
"""

from sase.axe.run_agent_successor_delivery import (
    deliver_staged_successor_detached,
    mark_detached_successor_started_from_environment,
    mark_staged_successor_started,
)
from sase.axe.run_agent_successor_model import write_followup_model_meta
from sase.axe.run_agent_successor_staged import continue_as_successor
from sase.axe.run_agent_successor_staged_identity import (
    restore_staged_successor_in_loop,
)
from sase.axe.run_agent_successor_types import (
    FollowupModel,
    STAGED_SUCCESSOR_ID_ENV,
    STAGED_SUCCESSOR_ORIGIN_DIR_ENV,
    SuccessorDeliveryResult,
    SuccessorRequest,
)

__all__ = [
    "FollowupModel",
    "SuccessorDeliveryResult",
    "SuccessorRequest",
    "STAGED_SUCCESSOR_ID_ENV",
    "STAGED_SUCCESSOR_ORIGIN_DIR_ENV",
    "continue_as_successor",
    "deliver_staged_successor_detached",
    "mark_detached_successor_started_from_environment",
    "mark_staged_successor_started",
    "restore_staged_successor_in_loop",
    "write_followup_model_meta",
]
