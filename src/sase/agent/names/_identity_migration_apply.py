"""Apply-time mutation helpers for identity migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from sase.agent.names._identity_migration import (
    AgentIdentityMigrationError,
    AgentIdentityMigrationFileAction,
    AgentIdentityMigrationPreview,
)
from sase.agent.names._identity_migration_common import sha256
from sase.core.paths import sase_home


def apply_preview_actions(preview: AgentIdentityMigrationPreview) -> None:
    actions = preview.actions
    _revalidate_actions(actions)
    _apply_actions_atomic(actions)
    _validate_rewritten_json(actions)
    _run_projection_hooks_if_current_home(preview)


def _revalidate_actions(
    actions: tuple[AgentIdentityMigrationFileAction, ...],
) -> None:
    for action in actions:
        source = Path(action.source_path)
        try:
            current = source.read_bytes()
        except OSError as exc:
            raise AgentIdentityMigrationError(
                f"stale preview: could not read {source}: {exc}"
            ) from exc
        if (
            action.preimage_sha256 is not None
            and sha256(current) != action.preimage_sha256
        ):
            raise AgentIdentityMigrationError(f"stale preview: {source} changed")
        destination = Path(action.destination_path or action.source_path)
        if action.kind == "rename" and destination != source and destination.exists():
            try:
                existing = destination.read_bytes()
            except OSError as exc:
                raise AgentIdentityMigrationError(
                    f"stale preview: could not read destination {destination}: {exc}"
                ) from exc
            if action.postimage_bytes is None or existing != action.postimage_bytes:
                raise AgentIdentityMigrationError(
                    f"stale preview: destination exists: {destination}"
                )


def _apply_actions_atomic(
    actions: tuple[AgentIdentityMigrationFileAction, ...],
) -> None:
    backups: dict[Path, bytes | None] = {}
    created_destinations: set[Path] = set()
    stage = Path(tempfile.mkdtemp(prefix=".sase-identity-migration-"))
    try:
        staged: dict[AgentIdentityMigrationFileAction, Path] = {}
        for index, action in enumerate(actions):
            if action.postimage_bytes is None and action.kind != "delete":
                raise AgentIdentityMigrationError(
                    f"planned action has no postimage bytes: {action.source_path}"
                )
            staged_path = stage / f"{index}.payload"
            if action.postimage_bytes is not None:
                staged_path.write_bytes(action.postimage_bytes)
            staged[action] = staged_path
        for action in sorted(actions, key=_action_sort_key):
            source = Path(action.source_path)
            destination = Path(action.destination_path or action.source_path)
            for path in (source, destination):
                if path not in backups:
                    backups[path] = path.read_bytes() if path.exists() else None
            if action.kind == "delete":
                source.unlink()
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                created_destinations.add(destination)
            _atomic_write(destination, staged[action].read_bytes())
            if action.kind == "rename" and source != destination:
                source.unlink()
    except Exception:
        for path, original in reversed(tuple(backups.items())):
            if original is None:
                if path in created_destinations:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, original)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _action_sort_key(action: AgentIdentityMigrationFileAction) -> tuple[str, str, str]:
    return (action.path, action.kind, action.source_path)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=f".{os.getpid()}.tmp", dir=path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _validate_rewritten_json(
    actions: tuple[AgentIdentityMigrationFileAction, ...],
) -> None:
    for action in actions:
        destination = Path(action.destination_path or action.source_path)
        if destination.suffix not in {".json", ".jsonl"}:
            continue
        if destination.suffix == ".jsonl":
            for line in destination.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
            continue
        value = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AgentIdentityMigrationError(
                f"rewritten JSON is not an object: {destination}"
            )


def _run_projection_hooks_if_current_home(
    preview: AgentIdentityMigrationPreview,
) -> None:
    state_root = preview.request.state_path.resolve(strict=False)
    try:
        current_home = sase_home().resolve(strict=False)
    except OSError:
        return
    if state_root != current_home:
        return
    try:
        from sase.agent.names._registry import rebuild_name_registry
        from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index
        from sase.core.agent_artifact_index_lifecycle import (
            sync_dismissed_agent_artifact_index,
        )
        from sase.core.agent_scan_facade import (
            default_agent_artifact_index_path,
            rebuild_agent_artifact_index,
        )

        rebuild_name_registry()
        rebuild_agent_artifact_index(
            default_agent_artifact_index_path(current_home),
            preview.request.projects_path,
        )
        rebuild_dismissed_bundle_index()
        sync_dismissed_agent_artifact_index(force=True)
    except Exception as exc:
        raise AgentIdentityMigrationError(
            f"migration applied but projection regeneration failed: {exc}"
        ) from exc
