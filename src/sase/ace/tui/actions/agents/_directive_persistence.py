"""Worker-safe persistence for TUI edits to xprompt-backed agent properties."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.paths import sase_home
from sase.history.prompt_store import PromptHistoryLoadError, rewrite_prompt_text_exact
from sase.xprompt._directive_time import parse_absolute_time, parse_duration


@dataclass(frozen=True)
class AgentMetaPatch:
    """Patch to apply to ``agent_meta.json``."""

    set_values: Mapping[str, object] = field(default_factory=dict)
    remove_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTribeStorePatch:
    """Patch to apply to the persistent Agents-tab tribe store."""

    identity: tuple[Any, str, str | None]
    tribe: str | None


@dataclass(frozen=True)
class _WaitingMarkerPatch:
    """Replacement contents for ``waiting.json``."""

    waiting_for: tuple[str, ...] = ()
    wait_for_beads: tuple[str, ...] = ()
    wait_duration: float | None = None
    wait_until: str | None = None
    update_wait_runners: bool = False
    wait_runners: int | None = None
    update_wait_priority: bool = False
    wait_priority: int | None = None


@dataclass(frozen=True)
class ReadyMarkerPatch:
    """Replacement contents for ``ready.json``."""

    resolved_deps: tuple[str, ...] = ()
    unwait: bool = False


@dataclass(frozen=True)
class AgentDirectivePersistenceSpec:
    """All disk mutations for one xprompt directive-backed property edit."""

    artifacts_dir: str | Path | None
    prompt_mutator: Callable[[str], str] | None = None
    meta_patch: AgentMetaPatch | None = None
    tribe_patch: AgentTribeStorePatch | None = None
    waiting_marker: _WaitingMarkerPatch | None = None
    ready_marker: ReadyMarkerPatch | None = None


@dataclass(frozen=True)
class AgentDirectivePersistenceResult:
    """Summary of worker-side persistence effects."""

    raw_prompt_updated: bool = False
    submitted_prompt_updated: bool = False
    history_rewrites: int = 0
    stash_rewrites: int = 0
    meta_updated: bool = False
    waiting_updated: bool = False
    ready_updated: bool = False
    tribe_updated: bool = False


def persist_agent_directive_update(
    spec: AgentDirectivePersistenceSpec,
) -> AgentDirectivePersistenceResult:
    """Persist one agent directive update from a worker thread."""
    artifacts_path = (
        Path(spec.artifacts_dir).expanduser()
        if spec.artifacts_dir is not None
        else None
    )
    lock = (
        _agent_directive_lock(artifacts_path)
        if artifacts_path is not None
        else nullcontext()
    )
    with lock:
        result = AgentDirectivePersistenceResult()
        if spec.prompt_mutator is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for prompt rewrites")
            result = _persist_prompt_artifacts(artifacts_path, spec.prompt_mutator)
        if spec.meta_patch is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for agent_meta updates")
            meta_updated = _patch_agent_meta(artifacts_path, spec.meta_patch)
            result = replace(result, meta_updated=meta_updated)
        if spec.tribe_patch is not None:
            tribe_updated = _patch_agent_tribe_store(spec.tribe_patch)
            result = replace(result, tribe_updated=tribe_updated)
        if spec.waiting_marker is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for waiting marker updates")
            _write_waiting_marker(artifacts_path, spec.waiting_marker)
            result = replace(result, waiting_updated=True)
        if spec.ready_marker is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for ready marker updates")
            _write_ready_marker(artifacts_path, spec.ready_marker)
            result = replace(result, ready_updated=True)
        return result


def wait_meta_patch_for_token(
    *,
    wait_names: tuple[str, ...] = (),
    wait_beads: tuple[str, ...] = (),
    time_token: str | None = None,
    update_wait_runners: bool = False,
    wait_runners: int | None = None,
    update_wait_priority: bool = False,
    wait_priority: int | None = None,
) -> AgentMetaPatch:
    """Build an ``agent_meta.json`` patch for a wait directive payload."""
    set_values: dict[str, object] = {}
    remove_keys = ["wait_for", "wait_for_beads", "wait_duration", "wait_until"]
    if wait_names:
        set_values["wait_for"] = list(_durable_wait_names(wait_names))
    if wait_beads:
        set_values["wait_for_beads"] = list(wait_beads)
    if time_token:
        duration = parse_duration(time_token)
        if duration is not None:
            set_values["wait_duration"] = duration
        else:
            wait_until = parse_absolute_time(time_token)
            if wait_until is not None:
                set_values["wait_until"] = wait_until
    if update_wait_runners:
        remove_keys.append("wait_runners")
        if wait_runners is not None:
            set_values["wait_runners"] = wait_runners
    if update_wait_priority:
        remove_keys.append("wait_priority")
        if wait_priority is not None:
            set_values["wait_priority"] = wait_priority
    return AgentMetaPatch(set_values=set_values, remove_keys=tuple(remove_keys))


def waiting_marker_patch_for_token(
    *,
    wait_names: tuple[str, ...] = (),
    wait_beads: tuple[str, ...] = (),
    time_token: str | None = None,
    update_wait_runners: bool = False,
    wait_runners: int | None = None,
    update_wait_priority: bool = False,
    wait_priority: int | None = None,
) -> _WaitingMarkerPatch:
    """Build a ``waiting.json`` replacement for a wait directive payload."""
    wait_duration: float | None = None
    wait_until: str | None = None
    if time_token:
        wait_duration = parse_duration(time_token)
        if wait_duration is None:
            wait_until = parse_absolute_time(time_token)
    return _WaitingMarkerPatch(
        waiting_for=_durable_wait_names(wait_names),
        wait_for_beads=wait_beads,
        wait_duration=wait_duration,
        wait_until=wait_until,
        update_wait_runners=update_wait_runners,
        wait_runners=wait_runners,
        update_wait_priority=update_wait_priority,
        wait_priority=wait_priority,
    )


def _durable_wait_names(wait_names: tuple[str, ...]) -> tuple[str, ...]:
    """Qualify agent dependencies while leaving tribe references unchanged."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    return tuple(
        name if name.startswith("@") else normalize_owned_agent_name(name, identity)
        for name in wait_names
    )


def _persist_prompt_artifacts(
    artifacts_path: Path,
    prompt_mutator: Callable[[str], str],
) -> AgentDirectivePersistenceResult:
    raw_path = artifacts_path / "raw_xprompt.md"
    try:
        old_prompt = raw_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AgentDirectivePersistenceResult()

    new_prompt = prompt_mutator(old_prompt)
    if new_prompt == old_prompt:
        return AgentDirectivePersistenceResult()

    _write_text_atomic(raw_path, new_prompt)

    submitted_updated = False
    submitted_path = artifacts_path / "submitted_xprompt.md"
    try:
        submitted_prompt = submitted_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        submitted_prompt = None
    if submitted_prompt == old_prompt:
        _write_text_atomic(submitted_path, new_prompt)
        submitted_updated = True

    try:
        history_rewrites = rewrite_prompt_text_exact(old_prompt, new_prompt)
    except PromptHistoryLoadError:
        history_rewrites = 0
    stash_rewrites = _rewrite_prompt_stash_exact(old_prompt, new_prompt)
    return AgentDirectivePersistenceResult(
        raw_prompt_updated=True,
        submitted_prompt_updated=submitted_updated,
        history_rewrites=history_rewrites,
        stash_rewrites=stash_rewrites,
    )


def _patch_agent_meta(artifacts_path: Path, patch: AgentMetaPatch) -> bool:
    meta_path = artifacts_path / "agent_meta.json"
    meta = _read_json_object(meta_path)
    original = dict(meta)
    canonicalize_agent_tribe_metadata(meta)
    for key in patch.remove_keys:
        meta.pop(key, None)
    meta.update(dict(patch.set_values))
    if meta == original:
        return False
    _write_json_file(meta_path, meta)
    update_agent_artifact_index_for_marker_mutation(str(artifacts_path))
    return True


def _patch_agent_tribe_store(patch: AgentTribeStorePatch) -> bool:
    from sase.ace.agent_tribes import update_agent_tribe_assignment

    return update_agent_tribe_assignment(patch.identity, patch.tribe)


def _write_waiting_marker(artifacts_path: Path, patch: _WaitingMarkerPatch) -> None:
    # Serialize with the admission poller's check/refresh critical section so
    # a parked agent cannot overwrite a just-saved threshold with the value it
    # read immediately before the TUI edit.
    with _runner_slot_marker_lock():
        waiting_path = artifacts_path / "waiting.json"
        existing = _read_json_object(waiting_path)
        for condition_key in (
            "waiting_for",
            "wait_for_beads",
            "wait_duration",
            "wait_until",
        ):
            existing.pop(condition_key, None)
        existing["waiting_for"] = list(patch.waiting_for)
        if patch.wait_for_beads:
            existing["wait_for_beads"] = list(patch.wait_for_beads)
        if patch.wait_duration is not None:
            existing["wait_duration"] = patch.wait_duration
        if patch.wait_until is not None:
            existing["wait_until"] = patch.wait_until
        if patch.update_wait_runners:
            existing.pop("wait_runners", None)
            existing["wait_runners_explicit"] = patch.wait_runners is not None
            if patch.wait_runners is not None:
                existing["wait_runners"] = patch.wait_runners
        if patch.update_wait_priority:
            existing.pop("wait_priority", None)
            existing["wait_priority_explicit"] = patch.wait_priority is not None
            if patch.wait_priority is not None:
                existing["wait_priority"] = patch.wait_priority
        _write_json_file(waiting_path, existing)
    update_agent_artifact_index_for_marker_mutation(str(artifacts_path))


def _write_ready_marker(artifacts_path: Path, patch: ReadyMarkerPatch) -> None:
    ready_path = artifacts_path / "ready.json"
    if ready_path.exists():
        raise FileExistsError(str(ready_path))
    data: dict[str, object] = {"resolved_deps": list(patch.resolved_deps)}
    if patch.unwait:
        data["unwait"] = True
    _write_json_file(ready_path, data)


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json_file(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(data), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _rewrite_prompt_stash_exact(old_prompt: str, new_prompt: str) -> int:
    try:
        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            read_prompt_stash_snapshot,
            rewrite_prompt_stash,
        )

        path = prompt_stash_path()
        snapshot = read_prompt_stash_snapshot(path)
        replacements = [
            replace(entry, text=new_prompt)
            for entry in snapshot.entries
            if entry.text == old_prompt
        ]
        if not replacements:
            return 0
        rewrite_prompt_stash(path, replacements)
        return len(replacements)
    except Exception:
        return 0


@contextmanager
def _agent_directive_lock(artifacts_path: Path) -> Iterator[None]:
    artifacts_path.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_path / ".agent_directive_persistence.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _runner_slot_marker_lock() -> Iterator[None]:
    lock_path = sase_home() / "runner_slots.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


__all__ = [
    "AgentDirectivePersistenceResult",
    "AgentDirectivePersistenceSpec",
    "AgentMetaPatch",
    "AgentTribeStorePatch",
    "ReadyMarkerPatch",
    "persist_agent_directive_update",
    "wait_meta_patch_for_token",
    "waiting_marker_patch_for_token",
]
