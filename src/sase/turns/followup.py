"""Follow-up launch support shared by agent-session turn kinds.

Facade preserving the original public import path. Implementation lives in
:mod:`sase.turns.followup_launch`, :mod:`sase.turns.followup_records`,
:mod:`sase.turns.followup_starter`, and :mod:`sase.turns._followup_common`.
"""

from __future__ import annotations

from ._followup_common import FollowupLaunchResult
from .followup_launch import (
    TurnFollowupWorkspace,
    launch_turn_followup,
    vcs_ref_from_meta,
)
from .followup_records import (
    FollowupPersistence,
    UpdateMetaFieldFn,
    persist_followup_prompt,
    record_followup_launched,
    record_followup_not_launchable,
    spawn_turn_agent_session_successor,
)
from .followup_starter import (
    DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    STARTER_SETTLE_POLL_SECONDS,
    fork_target_for_settled_starter,
    starter_identity,
    wait_for_followup_started,
    wait_for_starter,
    wait_for_starter_artifacts_dir,
)

__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "STARTER_SETTLE_POLL_SECONDS",
    "FollowupLaunchResult",
    "FollowupPersistence",
    "TurnFollowupWorkspace",
    "fork_target_for_settled_starter",
    "launch_turn_followup",
    "persist_followup_prompt",
    "record_followup_launched",
    "record_followup_not_launchable",
    "spawn_turn_agent_session_successor",
    "starter_identity",
    "vcs_ref_from_meta",
    "wait_for_followup_started",
    "wait_for_starter",
    "wait_for_starter_artifacts_dir",
]
