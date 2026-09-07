"""Wipe-closure planning for the agent-name wipe pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.names._wipe_payload import (
    payload_names,
    payload_outgoing_suffixes,
    read_json_object,
)
from sase.agent.names._wipe_scan import (
    ArtifactRecord,
    BundleRecord,
    WipeCatalog,
    load_wipe_catalog,
)


@dataclass
class WipePlan:
    target_name: str
    artifact_dirs: set[Path] = field(default_factory=set)
    bundle_paths: set[Path] = field(default_factory=set)
    suffixes: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)


def build_wipe_plan(
    owner: Mapping[str, Any],
    target_name: str,
    *,
    catalog: WipeCatalog | None = None,
) -> WipePlan:
    plan = WipePlan(target_name=target_name)
    plan.names.add(target_name)
    _seed_owner(plan, owner)

    if catalog is None:
        catalog = load_wipe_catalog()
    changed = True
    while changed:
        changed = False
        for artifact_record in catalog.artifacts:
            if (
                _artifact_related(artifact_record, plan)
                and artifact_record.path not in plan.artifact_dirs
            ):
                _add_artifact_record(plan, artifact_record)
                changed = True
        for bundle_record in catalog.bundles:
            if (
                _bundle_related(bundle_record, plan)
                and bundle_record.path not in plan.bundle_paths
            ):
                _add_bundle_record(plan, bundle_record)
                changed = True
    return plan


def merge_wipe_plans(plans: Sequence[WipePlan]) -> WipePlan:
    merged = WipePlan(target_name="batch")
    for plan in plans:
        merged.artifact_dirs.update(plan.artifact_dirs)
        merged.bundle_paths.update(plan.bundle_paths)
        merged.suffixes.update(plan.suffixes)
        merged.names.update(plan.names)
    return merged


def _seed_owner(plan: WipePlan, owner: Mapping[str, Any]) -> None:
    raw_suffix = owner.get("raw_suffix")
    if isinstance(raw_suffix, str) and raw_suffix:
        plan.suffixes.add(raw_suffix)

    for key in ("name", "workflow_name", "agent_name"):
        value = owner.get(key)
        if isinstance(value, str) and value:
            plan.names.add(value)

    artifacts_dir = owner.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        path = Path(artifacts_dir).expanduser().resolve(strict=False)
        plan.artifact_dirs.add(path)
        _seed_payload_path(plan, path / "agent_meta.json")
        _seed_payload_path(plan, path / "done.json")

    bundle_path = owner.get("bundle_path")
    if isinstance(bundle_path, str) and bundle_path:
        path = Path(bundle_path).expanduser().resolve(strict=False)
        plan.bundle_paths.add(path)
        _seed_payload_path(plan, path, bundle=True)


def _seed_payload_path(plan: WipePlan, path: Path, *, bundle: bool = False) -> None:
    payload = read_json_object(path)
    if payload is None:
        return
    plan.names.update(payload_names(payload, bundle=bundle))
    raw_suffix = payload.get("raw_suffix")
    if isinstance(raw_suffix, str) and raw_suffix:
        plan.suffixes.add(raw_suffix)
    plan.suffixes.update(payload_outgoing_suffixes(payload))


def _artifact_related(record: ArtifactRecord, plan: WipePlan) -> bool:
    return (
        record.path in plan.artifact_dirs
        or record.suffix in plan.suffixes
        or bool(record.names & plan.names)
        or bool(record.relation_refs & plan.suffixes)
    )


def _bundle_related(record: BundleRecord, plan: WipePlan) -> bool:
    return (
        record.path in plan.bundle_paths
        or (record.raw_suffix is not None and record.raw_suffix in plan.suffixes)
        or bool(record.names & plan.names)
        or bool(record.relation_refs & plan.suffixes)
    )


def _add_artifact_record(plan: WipePlan, record: ArtifactRecord) -> None:
    plan.artifact_dirs.add(record.path)
    plan.suffixes.add(record.suffix)
    plan.suffixes.update(record.outgoing_suffixes)
    plan.names.update(record.names)


def _add_bundle_record(plan: WipePlan, record: BundleRecord) -> None:
    plan.bundle_paths.add(record.path)
    if record.raw_suffix:
        plan.suffixes.add(record.raw_suffix)
    plan.suffixes.update(record.outgoing_suffixes)
    plan.names.update(record.names)
