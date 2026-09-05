"""Dry-run-first purge of every locally materialized agents-sync import.

The legacy v1 forget-import escape hatch (see ``v1_forget_import.py``) removes
one machine's fully-superseded legacy v1 closure at a time. This module
generalizes that pattern into one explicit sweep that purges every locally
materialized import closure regardless of transport, source machine, or
project: imported artifacts, chat files, dismissed bundles and identities,
import journals and staging, the incoming cache, and import receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from sase.agents_sync.incoming_cache_paths import (
    cache_objects_dir,
    cache_staging_dir,
    receipts_dir,
)
from sase.agents_sync.inventory_io import is_imported
from sase.agents_sync.v2_import_history import read_json_object
from sase.agents_sync.v2_import_storage import imports_root
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
    sync_dismissed_agent_artifact_index,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    iter_agent_artifact_dirs,
)
from sase.core.agent_types import AgentIdentity, AgentType
from sase.core.dismissed_agents_facade import (
    dismissed_bundles_dir,
    iter_dismissed_bundle_paths,
    load_dismissed_agents,
    persist_dismissed_agents as save_dismissed_agents,
    rebuild_dismissed_bundle_index,
)
from sase.core.paths import sase_projects_dir

_IMPORT_ORIGINS = frozenset({"import_v1", "import_v2"})


@dataclass(frozen=True, slots=True)
class PurgeLocalStateOutcome:
    """Truthful preview or mutation result for one full local-import sweep."""

    dry_run: bool
    artifact_dirs: tuple[Path, ...] = ()
    chat_files: tuple[Path, ...] = ()
    bundle_files: tuple[Path, ...] = ()
    dismissed_identities: tuple[AgentIdentity, ...] = ()
    import_dirs: tuple[Path, ...] = ()
    cache_dirs: tuple[Path, ...] = ()
    receipt_files: tuple[Path, ...] = ()
    surviving_import_names: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def is_empty(self) -> bool:
        """Return whether the scan found no locally materialized import state."""
        return not (
            self.artifact_dirs
            or self.chat_files
            or self.bundle_files
            or self.dismissed_identities
            or self.import_dirs
            or self.cache_dirs
            or self.receipt_files
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "mode": "dry-run" if self.dry_run else "apply",
            "artifact_dirs": [str(path) for path in self.artifact_dirs],
            "chat_files": [str(path) for path in self.chat_files],
            "bundle_files": [str(path) for path in self.bundle_files],
            "dismissed_identities": [
                {
                    "agent_type": str(kind),
                    "cl_name": cl_name,
                    "raw_suffix": raw_suffix,
                }
                for kind, cl_name, raw_suffix in self.dismissed_identities
            ],
            "import_dirs": [str(path) for path in self.import_dirs],
            "cache_dirs": [str(path) for path in self.cache_dirs],
            "receipt_files": [str(path) for path in self.receipt_files],
            "surviving_import_names": list(self.surviving_import_names),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class _Closure:
    """Exact local state one full import sweep would touch."""

    artifact_dirs: tuple[Path, ...]
    chat_files: tuple[Path, ...]
    bundle_files: tuple[Path, ...]
    dismissed_identities: tuple[AgentIdentity, ...]
    import_dirs: tuple[Path, ...]
    cache_dirs: tuple[Path, ...]
    receipt_files: tuple[Path, ...]


def purge_local_import_state(*, apply: bool = False) -> PurgeLocalStateOutcome:
    """Preview, or explicitly remove, every locally materialized import closure."""
    closure = _scan_closure()
    if not apply:
        return PurgeLocalStateOutcome(
            True,
            artifact_dirs=closure.artifact_dirs,
            chat_files=closure.chat_files,
            bundle_files=closure.bundle_files,
            dismissed_identities=closure.dismissed_identities,
            import_dirs=closure.import_dirs,
            cache_dirs=closure.cache_dirs,
            receipt_files=closure.receipt_files,
        )
    return _apply_closure(closure)


def _scan_closure() -> _Closure:
    projects_root = sase_projects_dir()
    artifact_dirs: list[Path] = []
    chat_files: list[Path] = []
    import_dirs: list[Path] = []
    if projects_root.is_dir():
        for project_dir in sorted(
            path for path in projects_root.iterdir() if path.is_dir()
        ):
            project_key = project_dir.name
            for artifact_dir in iter_agent_artifact_dirs(
                project_key,
                ACE_RUN_WORKFLOW_DIR,
                newest_first=False,
            ):
                meta = read_json_object(artifact_dir / "agent_meta.json")
                if meta is None:
                    continue
                done = read_json_object(artifact_dir / "done.json")
                if not is_imported(meta, done):
                    continue
                artifact_dirs.append(artifact_dir)
                raw_chat_path = meta.get("chat_path")
                if isinstance(raw_chat_path, str) and raw_chat_path:
                    chat_path = Path(raw_chat_path).expanduser()
                    if chat_path.name.startswith("imported-") and chat_path.is_file():
                        chat_files.append(chat_path)
            import_dir = imports_root(project_key)
            if import_dir.is_dir():
                import_dirs.append(import_dir)

    bundle_files: list[Path] = []
    dismissed_identities: set[AgentIdentity] = set()
    for path in iter_dismissed_bundle_paths(dismissed_bundles_dir()):
        bundle = read_json_object(path)
        if bundle is None or not is_imported(bundle, None):
            continue
        bundle_files.append(path)
        raw_suffix = bundle.get("raw_suffix")
        if not isinstance(raw_suffix, str) or not raw_suffix:
            raw_suffix = path.stem
        identity = _bundle_identity(bundle, raw_suffix)
        if identity is not None:
            dismissed_identities.add(identity)

    cache_dirs = tuple(
        path for path in (cache_objects_dir(), cache_staging_dir()) if path.is_dir()
    )
    receipts_root = receipts_dir()
    receipt_files = (
        tuple(sorted(receipts_root.glob("*.json"))) if receipts_root.is_dir() else ()
    )

    return _Closure(
        tuple(artifact_dirs),
        tuple(chat_files),
        tuple(sorted(bundle_files)),
        tuple(
            sorted(
                dismissed_identities, key=lambda item: (item[0], item[1], item[2] or "")
            )
        ),
        tuple(import_dirs),
        cache_dirs,
        receipt_files,
    )


def _bundle_identity(bundle: dict[str, Any], raw_suffix: str) -> AgentIdentity | None:
    agent_type = bundle.get("agent_type")
    cl_name = bundle.get("patch_name") or bundle.get("cl_name")
    if not isinstance(agent_type, str) or not isinstance(cl_name, str) or not cl_name:
        return None
    try:
        typed_agent_type = AgentType(agent_type)
    except ValueError:
        return None
    return (typed_agent_type, cl_name, raw_suffix)


def _apply_closure(closure: _Closure) -> PurgeLocalStateOutcome:
    errors: list[str] = []

    # Retire recovery metadata first so an interrupted purge cannot race an
    # importer recovery and resurrect files while they are being removed.
    for import_dir in closure.import_dirs:
        try:
            shutil.rmtree(import_dir)
        except OSError as exc:
            errors.append(f"{import_dir}: {exc}")

    removed_artifact_dirs: list[Path] = []
    for artifact_dir in closure.artifact_dirs:
        try:
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)
            removed_artifact_dirs.append(artifact_dir)
        except OSError as exc:
            errors.append(f"{artifact_dir}: {exc}")
    if removed_artifact_dirs:
        delete_agent_artifact_index_artifacts(removed_artifact_dirs)

    for chat_file in closure.chat_files:
        try:
            chat_file.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{chat_file}: {exc}")

    removed_bundles: list[Path] = []
    for bundle_file in closure.bundle_files:
        try:
            bundle_file.unlink(missing_ok=True)
            removed_bundles.append(bundle_file)
        except OSError as exc:
            errors.append(f"{bundle_file}: {exc}")
    _prune_empty_bundle_shards(removed_bundles)
    rebuild_dismissed_bundle_index()

    if closure.dismissed_identities:
        dismissed = load_dismissed_agents()
        updated = dismissed - set(closure.dismissed_identities)
        if updated != dismissed and not save_dismissed_agents(updated):
            errors.append("failed to save dismissed identities after purge")
    sync_dismissed_agent_artifact_index(force=True)

    for cache_dir in closure.cache_dirs:
        try:
            shutil.rmtree(cache_dir)
        except OSError as exc:
            errors.append(f"{cache_dir}: {exc}")

    for receipt_file in closure.receipt_files:
        try:
            receipt_file.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{receipt_file}: {exc}")

    from sase.agent.names import rebuild_name_registry

    registry = rebuild_name_registry()
    entries = registry.get("entries", {})
    surviving = tuple(
        sorted(
            name
            for name, entry in entries.items()
            if isinstance(entry, dict) and entry.get("origin") in _IMPORT_ORIGINS
        )
    )
    return PurgeLocalStateOutcome(
        False,
        artifact_dirs=closure.artifact_dirs,
        chat_files=closure.chat_files,
        bundle_files=closure.bundle_files,
        dismissed_identities=closure.dismissed_identities,
        import_dirs=closure.import_dirs,
        cache_dirs=closure.cache_dirs,
        receipt_files=closure.receipt_files,
        surviving_import_names=surviving,
        errors=tuple(errors),
    )


def _prune_empty_bundle_shards(paths: list[Path]) -> None:
    root = dismissed_bundles_dir().resolve(strict=False)
    for parent in sorted({path.parent for path in paths}, reverse=True):
        if parent.resolve(strict=False) == root:
            continue
        try:
            parent.rmdir()
        except OSError:
            continue


__all__ = ["PurgeLocalStateOutcome", "purge_local_import_state"]
