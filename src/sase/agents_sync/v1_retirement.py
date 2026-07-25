"""Evidence-gated retirement of legacy-v1 agents-sidecar payloads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import (
    DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
    ensure_agents_clone,
)
from sase.agents_sync.git_sync_transaction import sync_project_locked
from sase.agents_sync.incoming_cache_legacy import (
    legacy_group_machine_hood,
    legacy_manifest_groups,
)
from sase.agents_sync.io import atomic_write_json, read_manifest
from sase.agents_sync.models import (
    AgentsManifest,
    ExportCounts,
    IntegrationCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity


@dataclass(frozen=True, slots=True)
class _V1RetirementPlan:
    """One read-only, evidence-checked legacy-v1 retirement plan."""

    manifest_entries: tuple[str, ...] = ()
    payload_paths: tuple[str, ...] = ()
    uncovered_hoods: tuple[str, ...] = ()
    removes_manifest: bool = False

    @property
    def covered(self) -> bool:
        return not self.uncovered_hoods


@dataclass(frozen=True, slots=True)
class V1RetirementOutcome:
    """Truthful per-project preview or mutation result."""

    project_key: str
    project: str
    dry_run: bool
    manifest_entries: tuple[str, ...] = ()
    payload_paths: tuple[str, ...] = ()
    uncovered_hoods: tuple[str, ...] = ()
    committed: bool = False
    pushed: bool = False
    skip_reason: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.uncovered_hoods

    def to_json_dict(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "mode": "dry-run" if self.dry_run else "apply",
            "manifest_entries": list(self.manifest_entries),
            "payload_paths": list(self.payload_paths),
            "uncovered_hoods": list(self.uncovered_hoods),
            "committed": self.committed,
            "pushed": self.pushed,
            "skip_reason": self.skip_reason,
            "error": self.error,
        }


def _plan_v1_retirement(
    target: ProjectTarget,
    repo_root: Path,
    owner: AgentOwnerIdentity,
) -> _V1RetirementPlan:
    """Plan retirement only when v2 publishes every current-machine v1 hood."""

    manifest_path = repo_root / "manifest.json"
    if not manifest_path.is_file():
        return _V1RetirementPlan()

    manifest = read_manifest(manifest_path)
    owned_entries = tuple(
        entry for entry in manifest.entries if entry.machine == owner.machine_name
    )
    if not owned_entries:
        return _V1RetirementPlan()

    owned_manifest = AgentsManifest(owned_entries)
    owned_groups = legacy_manifest_groups(owned_manifest)
    owned_hoods = tuple(
        sorted(legacy_group_machine_hood(group)[1] for group in owned_groups)
    )
    owner_manifest = read_owner_manifest(
        repo_root,
        owner,
        V2ProjectIdentity(target.project_key, target.project),
    )
    published_hoods = owner_manifest.by_hood().keys()
    uncovered = tuple(sorted(set(owned_hoods) - published_hoods))
    entry_names = tuple(sorted(entry.name for entry in owned_entries))
    payload_paths = tuple(
        f"agents/{name}"
        for name in entry_names
        if (repo_root / "agents" / name).exists()
        or (repo_root / "agents" / name).is_symlink()
    )
    removes_manifest = len(owned_entries) == len(manifest.entries)
    return _V1RetirementPlan(
        manifest_entries=entry_names,
        payload_paths=(
            ("manifest.json", *payload_paths) if removes_manifest else payload_paths
        ),
        uncovered_hoods=uncovered,
        removes_manifest=removes_manifest,
    )


def _apply_v1_retirement(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    plan: _V1RetirementPlan,
) -> None:
    """Apply one already-current plan without touching another machine's data."""

    if not plan.covered:
        raise ValueError(_coverage_error(plan.uncovered_hoods))
    if not plan.manifest_entries:
        return

    manifest_path = repo_root / "manifest.json"
    manifest = read_manifest(manifest_path)
    selected = frozenset(plan.manifest_entries)
    current_owned = frozenset(
        entry.name for entry in manifest.entries if entry.machine == owner.machine_name
    )
    if current_owned != selected:
        raise RuntimeError("legacy-v1 manifest changed after retirement was planned")

    for name in plan.manifest_entries:
        bundle_dir = repo_root / "agents" / name
        if bundle_dir.parent != repo_root / "agents":
            raise RuntimeError(f"unsafe legacy-v1 bundle path: {name!r}")
        if bundle_dir.is_dir():
            shutil.rmtree(bundle_dir)
        elif bundle_dir.exists():
            bundle_dir.unlink()

    remaining = tuple(entry for entry in manifest.entries if entry.name not in selected)
    if remaining:
        atomic_write_json(manifest_path, AgentsManifest(remaining).to_json_dict())
    else:
        manifest_path.unlink()


def retire_v1_payloads(
    projects: Sequence[str] = (),
    *,
    apply: bool = False,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[V1RetirementOutcome, ...]:
    """Preview or explicitly retire current-owner v1 payloads per project."""

    selection = resolve_sync_targets(projects)
    outcomes = [
        V1RetirementOutcome(
            item.project_key,
            item.project,
            not apply,
            skip_reason=item.skip_reason,
            error=item.error,
        )
        for item in selection.outcomes
    ]
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            V1RetirementOutcome(
                target.project_key,
                target.project,
                not apply,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    for target in selection.targets:
        try:
            outcome = (
                _retire_project(
                    target,
                    owner,
                    git_runner=git_runner,
                    lock_timeout_seconds=timeout,
                )
                if apply
                else _preview_project(target, owner)
            )
        except Exception as exc:  # noqa: BLE001 - project-scoped maintenance error
            outcome = V1RetirementOutcome(
                target.project_key,
                target.project,
                not apply,
                error=f"legacy-v1 retirement failed: {exc}",
            )
        outcomes.append(outcome)
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


def _preview_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
) -> V1RetirementOutcome:
    if not (target.sidecar_path / ".git").exists():
        return V1RetirementOutcome(
            target.project_key,
            target.project,
            True,
            skip_reason="agents sidecar clone does not exist on this machine",
        )
    plan = _plan_v1_retirement(target, target.sidecar_path, owner)
    return _outcome_from_plan(target, plan, dry_run=True)


def _retire_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner,
    lock_timeout_seconds: float = DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
) -> V1RetirementOutcome:
    if not target.primary_checkout.is_dir():
        return V1RetirementOutcome(
            target.project_key,
            target.project,
            False,
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    if clone_error is not None:
        return V1RetirementOutcome(
            target.project_key,
            target.project,
            False,
            skip_reason=(
                clone_error if clone_error == "agents sync clone lock is busy" else None
            ),
            error=(
                None if clone_error == "agents sync clone lock is busy" else clone_error
            ),
        )

    plans: list[_V1RetirementPlan] = []

    def retire_pass(
        pass_target: ProjectTarget,
        repo: Path,
        pass_owner: AgentOwnerIdentity,
        _git_runner: GitRunner,
    ) -> tuple[IntegrationCounts, ExportCounts]:
        plan = _plan_v1_retirement(pass_target, repo, pass_owner)
        plans.append(plan)
        if not plan.covered:
            raise ValueError(_coverage_error(plan.uncovered_hoods))
        _apply_v1_retirement(repo, pass_owner, plan)
        return IntegrationCounts(), ExportCounts()

    lock_path = agents_git_dir(target.sidecar_path, git_runner) / (
        "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, lock_timeout_seconds) as acquired:
        if not acquired:
            return V1RetirementOutcome(
                target.project_key,
                target.project,
                False,
                skip_reason="agents sync lock is busy",
            )
        sync_outcome = sync_project_locked(
            target,
            owner,
            git_runner,
            retire_pass,
        )

    plan = plans[-1] if plans else _V1RetirementPlan()
    return _outcome_from_plan(
        target,
        plan,
        dry_run=False,
        sync_outcome=sync_outcome,
    )


def _outcome_from_plan(
    target: ProjectTarget,
    plan: _V1RetirementPlan,
    *,
    dry_run: bool,
    sync_outcome: SyncOutcome | None = None,
) -> V1RetirementOutcome:
    return V1RetirementOutcome(
        target.project_key,
        target.project,
        dry_run,
        manifest_entries=plan.manifest_entries,
        payload_paths=plan.payload_paths,
        uncovered_hoods=plan.uncovered_hoods,
        committed=sync_outcome.committed if sync_outcome is not None else False,
        pushed=sync_outcome.pushed if sync_outcome is not None else False,
        skip_reason=(sync_outcome.skip_reason if sync_outcome is not None else None),
        error=sync_outcome.error if sync_outcome is not None else None,
    )


def _coverage_error(uncovered_hoods: tuple[str, ...]) -> str:
    return (
        "refusing legacy-v1 retirement; current owner's v2 manifest does not "
        f"cover: {', '.join(uncovered_hoods)}"
    )


__all__ = [
    "V1RetirementOutcome",
    "retire_v1_payloads",
]
