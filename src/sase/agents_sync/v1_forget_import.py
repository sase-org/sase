"""Dry-run-first removal of a machine's fully-superseded legacy v1 payload.

The v2-adoption evidence matcher (see ``v2_import_v1_adoption.py``) refreshes
a legacy v1 artifact in place whenever a validated v2 hood proves it
supersedes it. Some v1 edges are never provably migratable this way — the
source machine stopped publishing v2, or the run predates v2 entirely. This
module is the explicit, dry-run-first escape hatch an operator reaches for
once they have decided a machine's legacy v1 payload is safe to discard.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from sase.agents_sync.incoming_cache_receipts import (
    read_project_receipts,
    remove_project_receipts,
)
from sase.agents_sync.io import AgentsSyncFormatError, validate_machine
from sase.agents_sync.v2_import_history import read_json_object
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
)
from sase.core.paths import sase_projects_dir

ReceiptKey = tuple[str, str | None, str, str]


@dataclass(frozen=True, slots=True)
class V1ForgetImportOutcome:
    """Truthful preview or mutation result for one legacy v1 machine sweep."""

    machine: str
    dry_run: bool
    artifact_dirs: tuple[Path, ...] = ()
    chat_files: tuple[Path, ...] = ()
    bundle_files: tuple[Path, ...] = ()
    dismissed_identities: tuple[AgentIdentity, ...] = ()
    receipts: tuple[tuple[str, ReceiptKey], ...] = ()
    surviving_import_v1_names: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json_dict(self) -> dict[str, object]:
        return {
            "machine": self.machine,
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
            "receipts": [
                {
                    "project_key": project_key,
                    "source_owner_kind": key[0],
                    "source_username": key[1],
                    "source_machine": key[2],
                    "top_hood": key[3],
                }
                for project_key, key in self.receipts
            ],
            "surviving_import_v1_names": list(self.surviving_import_v1_names),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class _Closure:
    """Exact local state a legacy v1 machine sweep would touch."""

    artifact_dirs: tuple[Path, ...]
    chat_files: tuple[Path, ...]
    bundle_files: tuple[Path, ...]
    dismissed_identities: tuple[AgentIdentity, ...]
    receipts: tuple[tuple[str, ReceiptKey], ...]


def forget_v1_import(machine: str, *, apply: bool = False) -> V1ForgetImportOutcome:
    """Preview, or explicitly remove, one machine's legacy v1 import closure."""

    machine = validate_machine(machine)
    closure = _scan_closure(machine)
    if not apply:
        return V1ForgetImportOutcome(
            machine,
            True,
            artifact_dirs=closure.artifact_dirs,
            chat_files=closure.chat_files,
            bundle_files=closure.bundle_files,
            dismissed_identities=closure.dismissed_identities,
            receipts=closure.receipts,
        )
    return _apply_closure(machine, closure)


def _scan_closure(machine: str) -> _Closure:
    projects_root = sase_projects_dir()
    if not projects_root.is_dir():
        return _Closure((), (), (), (), ())

    bundles_root = dismissed_bundles_dir()
    artifact_dirs: list[Path] = []
    chat_files: list[Path] = []
    bundle_files: list[Path] = []
    seen_bundle_paths: set[Path] = set()
    dismissed_identities: set[AgentIdentity] = set()
    receipts: list[tuple[str, ReceiptKey]] = []

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
            if (
                meta.get("imported_owner_kind") != "username_unknown_v1"
                or meta.get("imported_from_machine") != machine
            ):
                continue
            artifact_dirs.append(artifact_dir)
            raw_chat_path = meta.get("chat_path")
            if isinstance(raw_chat_path, str) and raw_chat_path:
                chat_path = Path(raw_chat_path).expanduser()
                if chat_path.name.startswith("imported-") and chat_path.is_file():
                    chat_files.append(chat_path)
            raw_suffix = artifact_dir.name
            for bundle_path in _matching_bundle_paths(
                bundles_root,
                raw_suffix,
                meta.get("name"),
                artifact_dir,
            ):
                if bundle_path in seen_bundle_paths:
                    continue
                seen_bundle_paths.add(bundle_path)
                bundle = read_json_object(bundle_path)
                if bundle is None:
                    continue
                bundle_files.append(bundle_path)
                identity = _bundle_identity(bundle, raw_suffix)
                if identity is not None:
                    dismissed_identities.add(identity)
        for receipt in read_project_receipts(project_key):
            if (
                receipt.source_owner_kind == "username_unknown_v1"
                and receipt.source_machine == machine
            ):
                receipts.append((project_key, receipt.source_hood_key))

    return _Closure(
        tuple(artifact_dirs),
        tuple(chat_files),
        tuple(bundle_files),
        tuple(
            sorted(
                dismissed_identities, key=lambda item: (item[0], item[1], item[2] or "")
            )
        ),
        tuple(receipts),
    )


def _matching_bundle_paths(
    bundles_root: Path,
    raw_suffix: str,
    v1_name: object,
    artifact_dir: Path,
) -> list[Path]:
    artifact_text = str(artifact_dir)
    matches: list[Path] = []
    for path in iter_dismissed_bundle_paths(
        bundles_root, pattern=f"{raw_suffix}*.json"
    ):
        bundle = read_json_object(path)
        if bundle is None:
            continue
        if bundle.get("agent_name") == v1_name or bundle.get("artifacts_dir") == (
            artifact_text
        ):
            matches.append(path)
    return matches


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


def _apply_closure(machine: str, closure: _Closure) -> V1ForgetImportOutcome:
    errors: list[str] = []
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

    for bundle_file in closure.bundle_files:
        try:
            bundle_file.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{bundle_file}: {exc}")

    if closure.dismissed_identities:
        dismissed = load_dismissed_agents()
        updated = dismissed - set(closure.dismissed_identities)
        if updated != dismissed and not save_dismissed_agents(updated):
            errors.append("failed to save dismissed identities after forget-import")
    sync_dismissed_agent_artifact_index(force=True)

    receipts_by_project: dict[str, list[ReceiptKey]] = {}
    for project_key, key in closure.receipts:
        receipts_by_project.setdefault(project_key, []).append(key)
    for project_key, keys in receipts_by_project.items():
        try:
            remove_project_receipts(project_key, keys)
        except (OSError, AgentsSyncFormatError) as exc:
            errors.append(f"{project_key}: {exc}")

    from sase.agent.names import rebuild_name_registry

    registry = rebuild_name_registry()
    entries = registry.get("entries", {})
    surviving = tuple(
        sorted(
            name
            for name, entry in entries.items()
            if isinstance(entry, dict)
            and entry.get("origin") == "import_v1"
            and entry.get("legacy_source_machine") == machine
        )
    )
    return V1ForgetImportOutcome(
        machine,
        False,
        artifact_dirs=closure.artifact_dirs,
        chat_files=closure.chat_files,
        bundle_files=closure.bundle_files,
        dismissed_identities=closure.dismissed_identities,
        receipts=closure.receipts,
        surviving_import_v1_names=surviving,
        errors=tuple(errors),
    )


__all__ = ["V1ForgetImportOutcome", "forget_v1_import"]
