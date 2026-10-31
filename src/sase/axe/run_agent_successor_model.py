"""Follow-up model metadata for the agent-session-successor engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_helpers import update_meta_field
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import LoopState
    from sase.axe.run_agent_successor_types import FollowupModel

_PLAN_ACCEPT_MODULE = "sase.axe.run_agent_exec_plan_accept"


def _accept_binding[T](name: str, default: T) -> T:
    """Prefer a plan-accept module binding so its test doubles still apply."""
    module = sys.modules.get(_PLAN_ACCEPT_MODULE)
    if module is None:
        return default
    return getattr(module, name, default)


def _write_followup_model_alias_meta(
    artifacts_dir: str,
    model_alias: str | None,
    model_alias_trail: tuple[str, ...],
    model_alias_origin: str | None,
) -> None:
    """Set or clear the follow-up agent's launch-time alias provenance."""
    write_atomic = _accept_binding("write_agent_meta_atomic", write_agent_meta_atomic)
    index_updater = _accept_binding(
        "update_agent_artifact_index_for_marker_mutation",
        update_agent_artifact_index_for_marker_mutation,
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as handle:
            meta = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(meta, dict):
        return
    if model_alias:
        meta["model_alias"] = model_alias
    else:
        meta.pop("model_alias", None)
    if model_alias_trail:
        meta["model_alias_trail"] = list(model_alias_trail)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    elif model_alias:
        meta.pop("model_alias_trail", None)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    else:
        meta.pop("model_alias_trail", None)
        meta.pop("model_alias_origin", None)
    write_atomic(
        artifacts_dir,
        meta,
        index_updater=index_updater,
    )


def write_followup_model_meta(state: LoopState, followup: FollowupModel) -> None:
    """Record the follow-up agent's resolved model in its ``agent_meta.json``."""
    if followup.meta is None:
        return
    update = _accept_binding("update_meta_field", update_meta_field)
    resolved_provider, resolved_model = followup.meta
    update(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update(state.current_artifacts_dir, "llm_provider", resolved_provider)
    _write_followup_model_alias_meta(
        state.current_artifacts_dir,
        followup.model_alias,
        followup.model_alias_trail,
        followup.model_alias_origin,
    )


__all__ = ["write_followup_model_meta"]
