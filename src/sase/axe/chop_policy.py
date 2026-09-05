"""Runner-owned declarative chop policy and bookkeeping host adapter.

The Rust chop engine owns validation and deterministic decisions. This module
supplies the public compatibility facade for IO-bound host snapshots and
checkpoint/once-per persistence helpers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sase.agent.running import list_running_agents
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records

from . import chop_policy_preflight as _preflight
from . import chop_policy_snapshots as _snapshots
from .chop_policy_checkpoint import (
    finalize_pending_chop_checkpoints,
    record_chop_checkpoint_event,
)
from .chop_policy_once_per import (
    NamedTemplateValue as _NamedTemplateValue,
    TargetTemplateValue as _TargetTemplateValue,
    apply_chop_once_per,
    once_per_relink_reason as _once_per_relink_reason,
    proposal_once_per_key as _proposal_once_per_key,
    release_chop_once_per_keys,
)
from .chop_policy_state import (
    checkpoint_path as _checkpoint_path,
    chop_policy_lock as _chop_policy_lock,
    read_checkpoint_document as _read_checkpoint_document,
    read_policy_document as _read_policy_document,
    read_seen_document as _read_seen_document,
    seen_path as _seen_path,
)
from .chop_policy_types import (
    ChopCheckpointEvent,
    ChopDecisionOutcome,
    ChopOncePerOutcome as _ChopOncePerOutcome,
    ChopPreflight,
    Proposal as _Proposal,
)
from .config import ChopConfig


@contextmanager
def _snapshot_dependency_overrides() -> Iterator[None]:
    """Honor legacy tests that patch dependencies on this facade module."""
    original_list_project_records = _snapshots.list_project_records
    original_list_running_agents = _snapshots.list_running_agents
    original_sase_home = _snapshots.sase_home
    original_sase_projects_dir = _snapshots.sase_projects_dir
    _snapshots.list_project_records = list_project_records
    _snapshots.list_running_agents = list_running_agents
    _snapshots.sase_home = sase_home
    _snapshots.sase_projects_dir = sase_projects_dir
    try:
        yield
    finally:
        _snapshots.list_project_records = original_list_project_records
        _snapshots.list_running_agents = original_list_running_agents
        _snapshots.sase_home = original_sase_home
        _snapshots.sase_projects_dir = original_sase_projects_dir


def evaluate_chop_preflight(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    context_file: str | None,
    scheduled: bool,
    force: bool = False,
    now: datetime | None = None,
) -> ChopPreflight:
    with _snapshot_dependency_overrides():
        return _preflight.evaluate_chop_preflight(
            lumberjack_name=lumberjack_name,
            chop=chop,
            context_file=context_file,
            scheduled=scheduled,
            force=force,
            now=now,
        )


def check_chop_trigger_runtime(chop: ChopConfig) -> str | None:
    with _snapshot_dependency_overrides():
        return _snapshots.check_chop_trigger_runtime(chop)


def _call_snapshot_helper(helper: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with _snapshot_dependency_overrides():
        return helper(*args, **kwargs)


def _module_getattr(name: str) -> Any:
    private_snapshot_helpers = {
        "_agent_snapshots": "agent_snapshots",
        "_compute_fs_trigger_token": "_compute_fs_trigger_token",
        "_fs_snapshot": "fs_snapshot",
        "_fs_watch_token": "_fs_watch_token",
        "_git_snapshot": "git_snapshot",
        "_patch_snapshots": "patch_snapshots",
        "_resolve_chop_git_project": "_resolve_chop_git_project",
        "_resolve_fs_watch_path": "_resolve_fs_watch_path",
        "_run_git": "run_git",
    }
    try:
        helper_name = private_snapshot_helpers[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    helper = getattr(_snapshots, helper_name)
    return lambda *args, **kwargs: _call_snapshot_helper(helper, *args, **kwargs)


__getattr__: Callable[[str], Any] = _module_getattr

__all__ = [
    "ChopCheckpointEvent",
    "ChopDecisionOutcome",
    "ChopPreflight",
    "apply_chop_once_per",
    "check_chop_trigger_runtime",
    "evaluate_chop_preflight",
    "finalize_pending_chop_checkpoints",
    "record_chop_checkpoint_event",
    "release_chop_once_per_keys",
]
