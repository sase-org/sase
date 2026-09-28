"""Sealed completion intent store: persist, load, bind, and rollback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import (
    bind_conditional_completion,
    preview_conditional_completion,
    rollback_conditional_completion_binding,
    validate_conditional_completion_intent,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers._prepare_shared import PreparedCompletion, command_argv
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    require_artifacts_dir,
)
from sase.finalizers.declaration_store import write_json_atomic
from sase.memory.locks import locked_file

COMPLETION_INTENTS_DIRNAME = "completion_intents"
COMPLETION_INDEX_FILENAME = "index.json"
COMPLETION_LOCK_FILENAME = "completion_intents.lock"


def persist_prepared_completion(
    intent: Mapping[str, Any],
    *,
    artifacts_dir: str | Path,
) -> PreparedCompletion:
    """Write a sealed intent under the agent's continuation store."""

    root = Path(artifacts_dir)
    intent_id = str(intent["intent_id"])
    directory = _intents_dir(root)
    path = directory / f"{_safe_filename(intent_id)}.json"
    with _intent_lock(root):
        write_json_atomic(path, intent)
        local_ref = f"local:continuation/{COMPLETION_INTENTS_DIRNAME}/{path.name}"
        artifact_ref = _register_explicit_artifact(path, root)
        refs = [local_ref, intent_id]
        if artifact_ref is not None:
            refs.insert(0, artifact_ref)
        _index_put(directory, intent_id, path.name, refs)
    intent_ref = refs[0]
    preview = preview_conditional_completion(dict(intent))
    return PreparedCompletion(
        intent=dict(intent),
        preview=preview,
        intent_ref=intent_ref,
        path=path,
    )


def load_prepared_completion(
    reference: str,
    *,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load a sealed intent by artifact ref, local ref, or intent id."""

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "conditional completion bind",
    )
    with _intent_lock(root):
        path = _resolve_intent_path(root, reference)
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalizerDeclarationError(
            f"conditional completion intent at {path} is not an object",
            code="malformed_completion_intent",
        )
    return validate_conditional_completion_intent(payload)


def bind_prepared_completion(
    reference: str,
    *,
    monitor_id: str,
    command: str | Sequence[str],
    request_fingerprint: str,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically bind a prepared intent to one monitor start."""

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "conditional completion bind",
    )
    argv = command_argv(command)
    with _intent_lock(root):
        path = _resolve_intent_path(root, reference)
        current = json.loads(path.read_text(encoding="utf-8"))
        try:
            bound = bind_conditional_completion(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "intent": current,
                    "monitor_id": monitor_id,
                    "command": argv,
                    "request_fingerprint": request_fingerprint,
                }
            )
        except ValueError as exc:
            raise FinalizerDeclarationError(
                str(exc),
                code="conditional_completion_bind_failed",
            ) from exc
        write_json_atomic(path, bound)
        return bound


def rollback_prepared_completion(
    reference: str,
    *,
    monitor_id: str,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Restore a bound intent after a failed monitor start."""

    try:
        root = require_artifacts_dir(
            str(artifacts_dir) if artifacts_dir is not None else None,
            "conditional completion rollback",
        )
    except FinalizerDeclarationError:
        return None
    with _intent_lock(root):
        try:
            path = _resolve_intent_path(root, reference)
            current = json.loads(path.read_text(encoding="utf-8"))
            restored = rollback_conditional_completion_binding(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "intent": current,
                    "monitor_id": monitor_id,
                }
            )
        except (FinalizerDeclarationError, OSError, ValueError, json.JSONDecodeError):
            return None
        write_json_atomic(path, restored)
        return restored


def _intents_dir(root: Path) -> Path:
    directory = root / "continuation" / COMPLETION_INTENTS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _intent_lock(root: Path) -> AbstractContextManager[None]:
    directory = _intents_dir(root)
    return locked_file(directory / COMPLETION_LOCK_FILENAME, fcntl.LOCK_EX)


def _index_put(
    directory: Path,
    intent_id: str,
    filename: str,
    refs: Sequence[str],
) -> None:
    index_path = directory / COMPLETION_INDEX_FILENAME
    index: dict[str, Any]
    if index_path.is_file():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        index = loaded if isinstance(loaded, dict) else {}
    else:
        index = {}
    intents = index.setdefault("intents", {})
    intents[intent_id] = {"filename": filename, "refs": list(refs)}
    aliases = index.setdefault("aliases", {})
    for ref in refs:
        aliases[ref] = intent_id
    write_json_atomic(index_path, index)


def _resolve_intent_path(root: Path, reference: str) -> Path:
    directory = _intents_dir(root)
    index_path = directory / COMPLETION_INDEX_FILENAME
    intent_id = reference
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}
        if isinstance(index, dict):
            aliases = index.get("aliases")
            if isinstance(aliases, dict) and reference in aliases:
                intent_id = str(aliases[reference])
            intents = index.get("intents")
            if isinstance(intents, dict) and intent_id in intents:
                record = intents[intent_id]
                if isinstance(record, dict) and isinstance(record.get("filename"), str):
                    path = directory / record["filename"]
                    if path.is_file():
                        return path
    candidate = directory / f"{_safe_filename(reference)}.json"
    if candidate.is_file():
        return candidate
    raise FinalizerDeclarationError(
        f"conditional completion intent {reference!r} was not found",
        code="missing_completion_intent",
    )


def _register_explicit_artifact(path: Path, artifacts_dir: Path) -> str | None:
    if os.environ.get("SASE_AGENT") != "1":
        return None
    try:
        from sase.core.artifact_file_facade import store_explicit_artifact_file

        artifact = store_explicit_artifact_file(
            path,
            artifacts_dir,
            label=f"conditional completion {path.stem}",
            kind="file",
        )
    except Exception:
        return None
    return f"file:{artifact.id}"


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in value)
