"""No-network cached integration and receipt-aware full-sync import."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
import re
import time

from sase.agents_sync.bundles import integrate_foreign_bundles
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_objects import FetchedAgentsCommit
from sase.agents_sync.incoming_cache import (
    cached_item_is_available,
    captured_incoming_hood_from_json,
    find_cached_evidence,
    legacy_group_digest,
    legacy_group_machine_hood,
    legacy_manifest_groups,
    load_validated_cache_item,
    prune_project_cache,
    read_project_receipts,
    receipt_for_item,
    write_import_receipt,
)
from sase.agents_sync.incoming_detection import (
    legacy_captured_item,
    v2_captured_item,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import (
    AgentHoodImportReceipt,
    AgentsManifest,
    CachedIntegrationDisposition,
    CachedIntegrationResult,
    CapturedIncomingHood,
    IntegrationCounts,
    ProjectTarget,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    discover_agent_imports,
)
from sase.agents_sync.v2_importer import integrate_v2_hoods
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    classify_agent_ownership,
)

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def integrate_cached_agent_updates(
    captured_items: Sequence[CapturedIncomingHood],
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[CachedIntegrationResult, ...]:
    """Integrate immutable cache objects with zero network or sidecar mutation."""

    items = tuple(captured_items)
    if not items:
        return ()
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        return tuple(
            _cached_result(
                item,
                "failed",
                f"owner identity is not configured: {exc}",
            )
            for item in items
        )
    selection = resolve_sync_targets(
        tuple(dict.fromkeys(item.project_key for item in items))
    )
    targets = {target.project_key: target for target in selection.targets}
    selection_errors = {
        outcome.project_key: outcome.error
        or outcome.skip_reason
        or "target unavailable"
        for outcome in selection.outcomes
    }
    results: list[CachedIntegrationResult | None] = [None] * len(items)
    grouped: dict[str, list[tuple[int, CapturedIncomingHood]]] = defaultdict(list)
    for index, item in enumerate(items):
        try:
            decoded = captured_incoming_hood_from_json(item.to_json_dict())
        except AgentsSyncFormatError as exc:
            results[index] = _cached_result(item, "failed", str(exc))
            continue
        target = targets.get(decoded.project_key)
        if target is None:
            results[index] = _cached_result(
                decoded,
                "failed",
                selection_errors.get(decoded.project_key, "project target unavailable"),
            )
            continue
        if decoded.project != target.project:
            results[index] = _cached_result(
                decoded,
                "failed",
                "captured project identity does not match current target",
            )
            continue
        grouped[decoded.project_key].append((index, decoded))

    from sase.agents_sync import git_sync

    timeout = (
        git_sync.configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    for project_key, rows in grouped.items():
        target = targets[project_key]
        git_dir = target.sidecar_path / ".git"
        if not git_dir.exists():
            for index, item in rows:
                results[index] = _cached_result(
                    item,
                    "failed",
                    "agents sidecar clone is unavailable for shared locking",
                )
            continue
        lock_path = (
            git_sync.agents_git_dir(target.sidecar_path, git_runner)
            / "sase-agents-sync.lock"
        )
        with git_sync.bounded_agents_lock(lock_path, timeout) as acquired:
            if not acquired:
                for index, item in rows:
                    results[index] = _cached_result(
                        item,
                        "failed",
                        "agents sync lock is busy",
                    )
                continue
            try:
                receipts = {
                    receipt.source_hood_key: receipt
                    for receipt in read_project_receipts(project_key)
                }
            except AgentsSyncFormatError as exc:
                for index, item in rows:
                    results[index] = _cached_result(
                        item,
                        "failed",
                        f"could not read import receipts: {exc}",
                    )
                continue
            for index, item in rows:
                result, receipt = _integrate_one_cached(
                    target,
                    item,
                    owner,
                    receipts.get(item.source_hood_key),
                )
                results[index] = result
                if receipt is not None:
                    receipts[receipt.source_hood_key] = receipt
        try:
            from sase.agents_sync.status import rewrite_agents_sync_status_after_sync

            rewrite_agents_sync_status_after_sync((project_key,))
        except Exception:
            pass
        prune_project_cache(
            project_key,
            pending_items=(),
            receipts=tuple(receipts.values()),
        )
    return tuple(
        result
        if result is not None
        else _cached_result(item, "failed", "cached integration did not run")
        for item, result in zip(items, results, strict=True)
    )


def integrate_agent_imports_with_receipts(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner = run_git,
) -> IntegrationCounts:
    """Run the full-sync import pass and advance the shared receipts."""

    discovery = discover_agent_imports(
        repo,
        V2ProjectIdentity(target.project_key, target.project),
    )
    identity = AgentIdentitySnapshot(owner)
    total = IntegrationCounts(diagnostics=discovery.diagnostics)
    for package in discovery.v2_packages:
        counts = integrate_v2_hoods(target, (package,), identity=identity)
        total = _merge_counts(total, counts)
        classification = classify_agent_ownership(
            AgentSourceOwnerIdentity.v2(package.owner),
            owner,
        )
        if (
            counts.hoods_quarantined == 0
            and classification is not AgentOwnershipClassification.EXACT_OWNER
        ):
            evidence = _direct_v2_evidence(
                target,
                repo,
                package,
                git_runner=git_runner,
            )
            write_import_receipt(receipt_for_item(evidence))

    legacy_diagnostics: list[str] = []
    for manifest in legacy_manifest_groups(discovery.legacy_manifest):
        try:
            counts = integrate_foreign_bundles(
                target,
                repo,
                manifest,
                owner.machine_name,
            )
            total = _merge_counts(total, counts)
            evidence = _direct_legacy_evidence(
                target,
                repo,
                manifest,
                git_runner=git_runner,
            )
            write_import_receipt(receipt_for_item(evidence))
        except Exception as exc:  # noqa: BLE001 - legacy group quarantine boundary
            machine, hood = legacy_group_machine_hood(manifest)
            legacy_diagnostics.append(
                f"{machine}.{hood}: quarantined legacy v1 import: {exc}"
            )
    if legacy_diagnostics:
        total = _merge_counts(
            total,
            IntegrationCounts(diagnostics=tuple(legacy_diagnostics)),
        )
    return total


def _integrate_one_cached(
    target: ProjectTarget,
    item: CapturedIncomingHood,
    owner: AgentOwnerIdentity,
    prior: AgentHoodImportReceipt | None,
) -> tuple[CachedIntegrationResult, AgentHoodImportReceipt | None]:
    if prior is not None and prior.hood_digest == item.hood_digest:
        return CachedIntegrationResult(item, "already_applied"), None
    if (
        prior is not None
        and prior.hood_digest != item.hood_digest
        and prior.cache_created_at >= item.cache_created_at
    ):
        return CachedIntegrationResult(item, "stale"), None
    if not cached_item_is_available(item):
        return CachedIntegrationResult(item, "missing"), None
    try:
        loaded = load_validated_cache_item(item)
    except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
        return _cached_result(item, "quarantined", str(exc)), None
    try:
        if loaded.v2_package is not None:
            counts = integrate_v2_hoods(
                target,
                (loaded.v2_package,),
                identity=AgentIdentitySnapshot(owner),
            )
            if counts.hoods_quarantined:
                return (
                    CachedIntegrationResult(
                        item,
                        "quarantined",
                        hoods_quarantined=counts.hoods_quarantined,
                        diagnostics=counts.diagnostics,
                    ),
                    None,
                )
        else:
            assert loaded.legacy_manifest is not None
            counts = integrate_foreign_bundles(
                target,
                loaded.payload_root,
                loaded.legacy_manifest,
                owner.machine_name,
            )
    except Exception as exc:  # noqa: BLE001 - import quarantine contract
        return _cached_result(item, "quarantined", str(exc)), None
    receipt = receipt_for_item(item)
    try:
        write_import_receipt(receipt)
    except Exception as exc:  # noqa: BLE001 - typed receipt failure contract
        return _cached_result(item, "failed", str(exc)), None
    return (
        CachedIntegrationResult(
            item,
            "applied",
            integrated=counts.integrated,
            refreshed=counts.refreshed,
            unchanged=counts.unchanged,
            hoods_imported=counts.hoods_imported,
            hoods_refreshed=counts.hoods_refreshed,
            hoods_unchanged=counts.hoods_unchanged,
            hoods_quarantined=counts.hoods_quarantined,
            families_imported=counts.families_imported,
            runs_imported=counts.runs_imported,
            diagnostics=counts.diagnostics,
        ),
        receipt,
    )


def _direct_v2_evidence(
    target: ProjectTarget,
    repo: Path,
    package: ValidatedV2HoodPackage,
    *,
    git_runner: GitRunner,
) -> CapturedIncomingHood:
    matching = find_cached_evidence(
        target.project_key,
        (
            "exact",
            package.owner.username,
            package.owner.machine_name,
            package.hood,
        ),
        package.entry.digest,
    )
    if matching is not None:
        return matching
    fetched = FetchedAgentsCommit("HEAD", _head_sha(repo, git_runner))
    return v2_captured_item(
        target,
        fetched,
        package.manifest,
        package.hood,
        time.time(),
    )


def _direct_legacy_evidence(
    target: ProjectTarget,
    repo: Path,
    manifest: AgentsManifest,
    *,
    git_runner: GitRunner,
) -> CapturedIncomingHood:
    machine, hood = legacy_group_machine_hood(manifest)
    key = ("username_unknown_v1", None, machine, hood)
    digest = legacy_group_digest(manifest)
    matching = find_cached_evidence(target.project_key, key, digest)
    if matching is not None:
        return matching
    fetched = FetchedAgentsCommit("HEAD", _head_sha(repo, git_runner))
    return legacy_captured_item(target, fetched, manifest, time.time())


def _head_sha(repo: Path, git_runner: GitRunner) -> str:
    result = git_runner(
        repo,
        ["rev-parse", "--verify", "HEAD^{commit}"],
        op="agents_sync.receipt_head",
    )
    sha = result.stdout.strip().lower()
    if result.returncode != 0 or _SHA_RE.fullmatch(sha) is None:
        detail = (result.stderr or result.stdout or "unknown git error").strip()
        raise AgentsSyncFormatError(f"could not resolve receipt commit: {detail}")
    return sha


def _merge_counts(
    left: IntegrationCounts,
    right: IntegrationCounts,
) -> IntegrationCounts:
    return IntegrationCounts(
        integrated=left.integrated + right.integrated,
        refreshed=left.refreshed + right.refreshed,
        unchanged=left.unchanged + right.unchanged,
        hoods_imported=left.hoods_imported + right.hoods_imported,
        hoods_refreshed=left.hoods_refreshed + right.hoods_refreshed,
        hoods_unchanged=left.hoods_unchanged + right.hoods_unchanged,
        hoods_quarantined=left.hoods_quarantined + right.hoods_quarantined,
        families_imported=left.families_imported + right.families_imported,
        runs_imported=left.runs_imported + right.runs_imported,
        diagnostics=tuple(dict.fromkeys((*left.diagnostics, *right.diagnostics))),
    )


def _cached_result(
    item: CapturedIncomingHood,
    disposition: CachedIntegrationDisposition,
    diagnostic: str,
) -> CachedIntegrationResult:
    if disposition not in {"failed", "quarantined"}:
        raise AssertionError(f"unsupported diagnostic disposition: {disposition}")
    return CachedIntegrationResult(
        item,
        disposition,
        diagnostics=(diagnostic,),
    )


__all__ = [
    "integrate_agent_imports_with_receipts",
    "integrate_cached_agent_updates",
]
