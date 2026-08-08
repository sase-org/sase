"""Repair invalid future-dated state written by historical agent imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any

from sase.core.agent_types import AgentType
from sase.agents_sync.inventory_io import is_imported
from sase.core.paths import sase_home

_TIMESTAMP_RE = re.compile(r"^\d{14}$")
DismissedIdentity = tuple[AgentType, str, str | None]


@dataclass(frozen=True)
class _ImportedStateRepairPlan:
    """Exact future-imported paths and projections selected for repair."""

    artifacts: tuple[Path, ...]
    bundles: tuple[Path, ...]
    dismissed_identities: frozenset[DismissedIdentity]
    journals: tuple[Path, ...]
    registry_names: tuple[str, ...]
    transaction_keys: frozenset[str]

    def counts(self) -> dict[str, int]:
        """Return the categorized operator summary."""
        artifact_rows = len(self.artifacts)
        dismissed_rows = len(self.dismissed_identities)
        return {
            "artifacts": artifact_rows,
            "bundles": len(self.bundles),
            "index_rows": artifact_rows + dismissed_rows,
            "journals": len(self.journals),
            "registry_entries": len(self.registry_names),
        }


def plan_imported_state_repair(
    projects_root: Path,
    *,
    now: datetime | None = None,
) -> _ImportedStateRepairPlan:
    """Find future-dated imported state without mutating it."""
    cutoff = (now or datetime.now(tz=UTC)).astimezone(UTC)
    journal_paths, journal_transaction_keys = _future_import_journals(
        projects_root, cutoff
    )
    artifacts, artifact_identities, artifact_keys = _future_import_artifacts(
        projects_root,
        cutoff,
        journal_transaction_keys,
    )
    bundles, bundle_identities, bundle_keys = _future_import_bundles(
        cutoff,
        journal_transaction_keys,
    )
    transaction_keys = journal_transaction_keys | artifact_keys | bundle_keys
    journals = _journals_for_transaction_keys(
        projects_root,
        transaction_keys,
        seeded=journal_paths,
    )
    registry_names = _matching_registry_names(set(artifacts), set(bundles))
    return _ImportedStateRepairPlan(
        artifacts=tuple(sorted(artifacts)),
        bundles=tuple(sorted(bundles)),
        dismissed_identities=frozenset(artifact_identities | bundle_identities),
        journals=tuple(sorted(journals)),
        registry_names=tuple(sorted(registry_names)),
        transaction_keys=frozenset(transaction_keys),
    )


def apply_imported_state_repair(
    plan: _ImportedStateRepairPlan,
    *,
    index_path: Path,
) -> dict[str, int]:
    """Apply an exact repair plan and rebuild affected projections."""
    from sase.core.agent_artifact_index_lifecycle import (
        delete_agent_artifact_index_artifacts,
    )

    # Retire recovery metadata first so an interrupted repair cannot race an
    # importer recovery and resurrect files while they are being removed.
    _remove_journals_and_staging(plan.journals)
    removed_artifacts = _remove_artifacts(plan.artifacts)
    delete_agent_artifact_index_artifacts(removed_artifacts, index_path=index_path)
    removed_bundles = _remove_files(plan.bundles)
    _prune_empty_bundle_shards(removed_bundles)
    _rebuild_dismissed_bundle_index()
    _remove_dismissed_identities(plan.dismissed_identities, index_path)
    _rebuild_name_registry()
    return {
        **plan.counts(),
        "artifacts_removed": len(removed_artifacts),
        "bundles_removed": len(removed_bundles),
        "journals_removed": sum(not path.exists() for path in plan.journals),
    }


def _future_import_artifacts(
    projects_root: Path,
    cutoff: datetime,
    journal_transaction_keys: set[str],
) -> tuple[set[Path], set[DismissedIdentity], set[str]]:
    artifacts: set[Path] = set()
    identities: set[DismissedIdentity] = set()
    transaction_keys: set[str] = set()
    if not projects_root.is_dir():
        return artifacts, identities, transaction_keys
    for path in projects_root.glob("*/artifacts/**"):
        if not path.is_dir() or not _is_future_timestamp(path.name, cutoff):
            continue
        meta = _read_json_object(path / "agent_meta.json")
        done = _read_json_object(path / "done.json")
        transaction_key = _transaction_key(meta, done)
        if not is_imported(meta or {}, done) and (
            transaction_key is None or transaction_key not in journal_transaction_keys
        ):
            continue
        artifacts.add(path.resolve(strict=False))
        transaction_keys.update(_transaction_keys(meta, done))
        identity = _artifact_identity(path, projects_root, meta, done)
        if identity is not None:
            identities.add(identity)
    return artifacts, identities, transaction_keys


def _future_import_bundles(
    cutoff: datetime,
    journal_transaction_keys: set[str],
) -> tuple[set[Path], set[DismissedIdentity], set[str]]:
    from sase.ace.dismissed_agents import dismissed_bundles_dir

    bundles: set[Path] = set()
    identities: set[DismissedIdentity] = set()
    transaction_keys: set[str] = set()
    root = dismissed_bundles_dir()
    if not root.is_dir():
        return bundles, identities, transaction_keys
    for path in root.rglob("*.json"):
        bundle = _read_json_object(path)
        if bundle is None:
            continue
        raw_suffix = _text(bundle.get("raw_suffix")) or path.stem
        if not _is_future_timestamp(raw_suffix, cutoff):
            continue
        transaction_key = _transaction_key(bundle)
        if not is_imported(bundle, None) and (
            transaction_key is None or transaction_key not in journal_transaction_keys
        ):
            continue
        bundles.add(path.resolve(strict=False))
        transaction_keys.update(_transaction_keys(bundle))
        identity = _bundle_identity(bundle, raw_suffix)
        if identity is not None:
            identities.add(identity)
    return bundles, identities, transaction_keys


def _future_import_journals(
    projects_root: Path,
    cutoff: datetime,
) -> tuple[set[Path], set[str]]:
    paths: set[Path] = set()
    transaction_keys: set[str] = set()
    if not projects_root.is_dir():
        return paths, transaction_keys
    for path in projects_root.glob("*/agents_sync_imports/journals/*.json"):
        journal = _read_json_object(path)
        if journal is None or not _journal_has_future_destination(journal, cutoff):
            continue
        key = _text(journal.get("transaction_key"))
        if key is None:
            continue
        paths.add(path.resolve(strict=False))
        transaction_keys.add(key)
    return paths, transaction_keys


def _journals_for_transaction_keys(
    projects_root: Path,
    transaction_keys: set[str],
    *,
    seeded: set[Path],
) -> set[Path]:
    paths = set(seeded)
    if not transaction_keys or not projects_root.is_dir():
        return paths
    for path in projects_root.glob("*/agents_sync_imports/journals/*.json"):
        journal = _read_json_object(path)
        if (
            journal is not None
            and _text(journal.get("transaction_key")) in transaction_keys
        ):
            paths.add(path.resolve(strict=False))
    return paths


def _journal_has_future_destination(
    journal: dict[str, Any],
    cutoff: datetime,
) -> bool:
    relatives: list[object] = list(journal.get("artifact_relatives") or [])
    relatives.extend(
        row.get("relative")
        for row in journal.get("files") or []
        if isinstance(row, dict) and row.get("destination_kind") == "bundles"
    )
    return any(
        isinstance(relative, str) and _is_future_timestamp(Path(relative).stem, cutoff)
        for relative in relatives
    )


def _artifact_identity(
    path: Path,
    projects_root: Path,
    meta: dict[str, Any] | None,
    done: dict[str, Any] | None,
) -> DismissedIdentity | None:
    cl_name = _first_text(
        (done or {}).get("patch_name"),
        (done or {}).get("cl_name"),
        (meta or {}).get("patch_name"),
        (meta or {}).get("changespec_name"),
        (meta or {}).get("cl_name"),
    )
    if cl_name is None:
        try:
            cl_name = path.relative_to(projects_root).parts[0]
        except (ValueError, IndexError):
            return None
    return (AgentType.RUNNING, cl_name, path.name)


def _bundle_identity(
    bundle: dict[str, Any],
    raw_suffix: str,
) -> DismissedIdentity | None:
    agent_type = _text(bundle.get("agent_type"))
    cl_name = _text(bundle.get("cl_name"))
    try:
        typed_agent_type = AgentType(agent_type or "")
    except ValueError:
        return None
    if cl_name is None:
        return None
    return (typed_agent_type, cl_name, raw_suffix)


def _matching_registry_names(
    artifact_paths: set[Path],
    bundle_paths: set[Path],
) -> set[str]:
    path = sase_home() / "agent_name_registry.json"
    registry = _read_json_object(path)
    entries = registry.get("entries") if registry is not None else None
    if not isinstance(entries, dict):
        return set()
    artifact_strings = {str(item) for item in artifact_paths}
    bundle_strings = {str(item) for item in bundle_paths}
    return {
        name
        for name, entry in entries.items()
        if isinstance(name, str)
        and isinstance(entry, dict)
        and (
            entry.get("artifacts_dir") in artifact_strings
            or entry.get("bundle_path") in bundle_strings
        )
    }


def _remove_artifacts(paths: tuple[Path, ...]) -> set[Path]:
    removed: set[Path] = set()
    for path in paths:
        if not path.exists():
            continue
        shutil.rmtree(path)
        removed.add(path)
    return removed


def _remove_files(paths: tuple[Path, ...]) -> set[Path]:
    removed: set[Path] = set()
    for path in paths:
        try:
            path.unlink()
            removed.add(path)
        except FileNotFoundError:
            continue
    return removed


def _prune_empty_bundle_shards(paths: set[Path]) -> None:
    from sase.ace.dismissed_agents import dismissed_bundles_dir

    root = dismissed_bundles_dir().resolve(strict=False)
    for parent in sorted({path.parent for path in paths}, reverse=True):
        if parent.resolve(strict=False) == root:
            continue
        try:
            parent.rmdir()
        except OSError:
            continue


def _remove_dismissed_identities(
    identities: frozenset[DismissedIdentity],
    index_path: Path,
) -> None:
    from sase.ace.dismissed_agents import (
        load_dismissed_agents,
        save_dismissed_agents,
    )
    from sase.core.agent_artifact_index_lifecycle import (
        sync_dismissed_agent_artifact_index,
    )

    dismissed = load_dismissed_agents()
    updated = dismissed - set(identities)
    if updated != dismissed and not save_dismissed_agents(updated):
        raise RuntimeError("failed to prune repaired dismissed-agent identities")
    sync_dismissed_agent_artifact_index(index_path=index_path, force=True)


def _remove_journals_and_staging(paths: tuple[Path, ...]) -> None:
    for path in paths:
        journal = _read_json_object(path)
        stage_relative = (
            _text(journal.get("stage_relative")) if journal is not None else None
        )
        path.unlink(missing_ok=True)
        if stage_relative is None:
            continue
        imports_root = path.parent.parent
        stage = (imports_root / stage_relative).resolve(strict=False)
        if stage.is_relative_to(imports_root.resolve(strict=False)):
            shutil.rmtree(stage, ignore_errors=True)


def _rebuild_dismissed_bundle_index() -> None:
    from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index

    rebuild_dismissed_bundle_index()


def _rebuild_name_registry() -> None:
    from sase.agent.names import rebuild_name_registry

    rebuild_name_registry()


def _is_future_timestamp(value: str, cutoff: datetime) -> bool:
    if _TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return False
    return parsed > cutoff


def _transaction_keys(*payloads: dict[str, Any] | None) -> set[str]:
    return {
        value
        for payload in payloads
        if payload is not None
        if (value := _text(payload.get("imported_transaction_key"))) is not None
    }


def _transaction_key(*payloads: dict[str, Any] | None) -> str | None:
    return next(iter(_transaction_keys(*payloads)), None)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _first_text(*values: object) -> str | None:
    return next((value for value in values if isinstance(value, str) and value), None)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "apply_imported_state_repair",
    "plan_imported_state_repair",
]
