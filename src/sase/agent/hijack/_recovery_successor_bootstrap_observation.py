"""Collect child-side facts used by the strict recovery bootstrap gate."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack._recovery_successor_common import (
    RECOVERY_LINEAGE_ENV,
    RecoveryInheritanceError,
    decode_recovery_lineage,
)


@dataclass(frozen=True)
class BootstrapObservation:
    """Child-side facts the bootstrap gate proves before provider execution.

    ``parent_repos``/``child_repos`` map opened-repository identities to
    their recorded workspace directories; ``None`` means the inventory could
    not be read (a missing predecessor inventory fails closed and must
    never pass as an empty one). ``parent_baseline``/``child_baseline``
    carry the commit-finalizer fingerprint maps (``None`` when unreadable).
    ``launch_identity`` is the child's own attempt identity from
    ``RECOVERY_LAUNCH_IDENTITY_ENV``. See :func:`collect_bootstrap_observation`.
    """

    successor_name: str | None
    process_token: str | None
    project: str | None
    workspace_num: int | None
    workspace_dir: str | None
    launch_identity: str | None
    provider: str | None
    model: str | None
    effort: str | None
    goal: str | None
    bead: str | None
    predecessor_goal: str | None
    predecessor_bead: str | None
    predecessor_autonomy: Mapping[str, Any] | None
    predecessor_name: str | None
    explicit_autonomy_selection: str | None
    parent_meta: Mapping[str, Any] | None
    child_meta: Mapping[str, Any] | None
    baseline_inherited: bool
    baseline_diagnostics: tuple[str, ...] = ()
    repo_diagnostics: tuple[str, ...] = ()
    predecessor_inventory_missing: bool = False
    parent_repos: Mapping[str, Any] | None = None
    child_repos: Mapping[str, Any] | None = None
    parent_baseline: Mapping[str, Any] | None = None
    child_baseline: Mapping[str, Any] | None = None
    lineage: Mapping[str, Any] | None = None


def collect_bootstrap_observation(
    *,
    child_artifacts_dir: str,
    parent_artifacts_dir: str | None,
    successor_name: str | None,
    process_token: str | None,
    project: str | None,
    workspace_num: int | None,
    workspace_dir: str | None,
    provider: str | None,
    model: str | None,
    effort: str | None,
    explicit_autonomy_selection: str | None = None,
    launch_identity: str | None = None,
) -> BootstrapObservation:
    """Collect the child-side facts the bootstrap gate must prove.

    Reads the predecessor's live ``agent_meta.json`` (goal, bead, permission
    record) and opened-repository inventory through the attach plan's parent
    artifacts directory, plus the child's own freshly written metadata,
    baselines, and inventory. Missing files degrade to ``None`` evidence
    that :func:`enforce_recovery_bootstrap` fails closed on; this function
    itself never raises for absent evidence.
    """
    from sase.history.chat_fork.common import load_json_object

    from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV

    if launch_identity is None:
        raw_launch = os.environ.get(RECOVERY_LAUNCH_IDENTITY_ENV)
        launch_identity = (
            raw_launch if isinstance(raw_launch, str) and raw_launch else None
        )
    parent_meta: Mapping[str, Any] | None = None
    if parent_artifacts_dir:
        loaded_parent = load_json_object(Path(parent_artifacts_dir) / "agent_meta.json")
        if isinstance(loaded_parent, Mapping) and loaded_parent:
            parent_meta = dict(loaded_parent)
    child_meta: Mapping[str, Any] | None = None
    loaded_child = load_json_object(Path(child_artifacts_dir) / "agent_meta.json")
    if isinstance(loaded_child, Mapping) and loaded_child:
        child_meta = dict(loaded_child)
    predecessor_autonomy: Mapping[str, Any] | None = None
    if parent_artifacts_dir:
        try:
            from sase.autonomy.record import live_record

            found = live_record(parent_artifacts_dir)
        except Exception:
            found = None
        if isinstance(found, Mapping) and found:
            predecessor_autonomy = dict(found)
    lineage: Mapping[str, Any] | None = None
    try:
        lineage = decode_recovery_lineage(
            os.environ.get(RECOVERY_LINEAGE_ENV)
        ).as_dict()
    except RecoveryInheritanceError:
        lineage = None
    return BootstrapObservation(
        successor_name=successor_name,
        process_token=process_token,
        project=project,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        launch_identity=launch_identity,
        provider=provider,
        model=model,
        effort=effort,
        goal=_meta_goal_value(child_meta),
        bead=_meta_bead_value(child_meta),
        predecessor_goal=_meta_goal_value(parent_meta),
        predecessor_bead=_meta_bead_value(parent_meta),
        predecessor_autonomy=predecessor_autonomy,
        predecessor_name=_meta_name_value(parent_meta),
        explicit_autonomy_selection=explicit_autonomy_selection,
        parent_meta=parent_meta,
        child_meta=child_meta,
        baseline_inherited=False,
        baseline_diagnostics=(),
        repo_diagnostics=(),
        predecessor_inventory_missing=parent_artifacts_dir is None
        or not Path(str(parent_artifacts_dir)).is_dir(),
        parent_repos=_read_opened_repo_inventory(parent_artifacts_dir),
        child_repos=_read_opened_repo_inventory(child_artifacts_dir),
        parent_baseline=_read_baseline_fingerprints(parent_artifacts_dir),
        child_baseline=_read_baseline_fingerprints(child_artifacts_dir),
        lineage=lineage,
    )


def _meta_goal_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the bound goal from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("goal_id", "goal"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _meta_bead_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the bead claim from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("bead_id", "bead"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _meta_name_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the agent name from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("name", "agent_name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_opened_repo_inventory(
    artifacts_dir: str | None,
) -> dict[str, str] | None:
    """Map opened-repository identities to workspace dirs, ``None`` if unreadable."""
    if not artifacts_dir or not Path(str(artifacts_dir)).is_dir():
        return None
    try:
        from sase._linked_repo_markers import opened_repo_records

        records = opened_repo_records(Path(str(artifacts_dir)))
    except Exception:
        return None
    inventory: dict[str, str] = {}
    for name, record in records.items():
        if not isinstance(record, Mapping):
            continue
        workspace_dir = record.get("workspace_dir")
        inventory[str(name)] = (
            str(workspace_dir) if isinstance(workspace_dir, str) else ""
        )
    return inventory


def _read_baseline_fingerprints(
    artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Load baseline fingerprint maps, ``None`` when unreadable or absent."""
    if not artifacts_dir or not Path(str(artifacts_dir)).is_dir():
        return None
    try:
        from sase.llm_provider.commit_finalizer_baseline import load_dirty_baseline

        found = load_dirty_baseline(Path(str(artifacts_dir)))
    except Exception:
        return None
    if found is None:
        return None
    try:
        return dict(found)
    except (TypeError, ValueError):
        return None
