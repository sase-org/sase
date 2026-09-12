"""Handoff and authored checkpoint publication for continuation capture."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

from ._storage import (
    PublicationTransaction,
    continuation_root,
    json_safe,
    recover_publication_journal,
    register_portable_capture_file,
    required_text,
    safe_identifier,
    sha_json,
    unique_identifiers,
    unique_refs,
    record_capture_error,
)

MAX_CHECKPOINT_BYTES = 256 * 1024


class AuthoredCheckpointError(ValueError):
    """The supplied checkpoint file is missing, too large, or malformed."""


@dataclass(frozen=True)
class AuthoredCheckpoint:
    """Canonical authored checkpoint document plus its content digest."""

    digest: str
    payload: dict[str, Any]
    coverage: tuple[str, ...]
    source_refs: tuple[str, ...]

    @property
    def content_ref(self) -> str:
        return f"sha256:{self.digest}"


def publish_handoff_checkpoint_best_effort(
    artifacts_dir: str | os.PathLike[str] | None,
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str | None:
    """Best-effort wrapper for handoff checkpoint publication."""

    if artifacts_dir is None:
        return None
    try:
        return publish_handoff_checkpoint(
            artifacts_dir,
            checkpoint_kind=checkpoint_kind,
            payload=payload,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, f"checkpoint:{checkpoint_kind}", exc)
        return None


def publish_handoff_checkpoint(
    artifacts_dir: str | os.PathLike[str],
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str:
    """Persist a content-addressed checkpoint and return its local ref."""

    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
    checkpoint_payload = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": checkpoint_kind,
        "payload": json_safe(payload),
        "recorded_at_epoch": time.time(),
    }
    digest = sha_json(checkpoint_payload)
    filename = f"{safe_identifier(checkpoint_kind)}-{digest[:16]}.json"
    txn = PublicationTransaction(root)
    ref, _ = txn.write_record("checkpoints", filename, payload=checkpoint_payload)
    txn.commit()
    return ref


def load_authored_checkpoint(path: str | os.PathLike[str]) -> AuthoredCheckpoint:
    """Parse a bounded YAML/JSON authored checkpoint from *path*."""

    checkpoint_path = Path(path).expanduser()
    try:
        raw = checkpoint_path.read_bytes()
    except OSError as exc:
        raise AuthoredCheckpointError(
            f"could not read -k/--checkpoint file {checkpoint_path}: {exc}"
        ) from exc
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise AuthoredCheckpointError(
            f"-k/--checkpoint file is {len(raw)} bytes; maximum is "
            f"{MAX_CHECKPOINT_BYTES} bytes"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthoredCheckpointError(
            f"-k/--checkpoint file is not valid UTF-8: {checkpoint_path}"
        ) from exc
    document = _parse_checkpoint_document(text, path=str(checkpoint_path))
    return canonicalize_authored_checkpoint(document)


def _parse_checkpoint_document(text: str, *, path: str) -> Mapping[str, Any]:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        import json

        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AuthoredCheckpointError(
                f"-k/--checkpoint {path} is not valid JSON: {exc}"
            ) from exc
    else:
        from sase._yaml_safe import yaml_safe_load

        try:
            loaded = yaml_safe_load(text)
        except Exception as exc:
            raise AuthoredCheckpointError(
                f"-k/--checkpoint {path} is not valid YAML: {exc}"
            ) from exc
    if not isinstance(loaded, Mapping):
        raise AuthoredCheckpointError(
            "-k/--checkpoint file must contain a JSON/YAML object"
        )
    return loaded


def canonicalize_authored_checkpoint(
    document: Mapping[str, Any],
) -> AuthoredCheckpoint:
    """Return the digest-stable authored checkpoint, excluding next-action text."""

    if "next_action" in document or "next" in document:
        raise AuthoredCheckpointError(
            "-k/--checkpoint must not include next-action text; pass it with -n/--next"
        )
    objective = _optional_text_or_list(document.get("objective"))
    constraints = _optional_text_or_list(document.get("constraints"))
    findings = _optional_text_or_list(document.get("findings"))
    unresolved = _optional_text_or_list(
        document.get("unresolved_decisions", document.get("unresolved_questions"))
    )
    remaining_work = _optional_text_or_list(document.get("remaining_work"))
    if not any((objective, constraints, findings, unresolved, remaining_work)):
        raise AuthoredCheckpointError(
            "-k/--checkpoint requires at least one of objective, constraints, "
            "findings, unresolved_decisions, or remaining_work"
        )
    coverage = tuple(unique_identifiers(_iter_string_values(document.get("coverage"))))
    source_refs = tuple(unique_refs(_iter_string_values(document.get("source_refs"))))
    author = _author_attribution(document.get("author"))
    payload: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "authored_checkpoint",
        "objective": objective,
        "constraints": constraints,
        "findings": findings,
        "unresolved_decisions": unresolved,
        "remaining_work": remaining_work,
        "source_refs": list(source_refs),
        "coverage": list(coverage),
        "author": author,
    }
    digest = sha_json(payload)
    return AuthoredCheckpoint(
        digest=digest,
        payload=payload,
        coverage=coverage,
        source_refs=source_refs,
    )


def persist_authored_checkpoint(
    artifacts_dir: str | os.PathLike[str],
    checkpoint: AuthoredCheckpoint,
    *,
    host_facts: Mapping[str, Any] | None = None,
    parent_ids: Sequence[str] = (),
    owner: Mapping[str, str] | None = None,
) -> str:
    """Persist an authored checkpoint immutably and return its local ref."""

    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
    filename = f"authored-{checkpoint.digest[:16]}.json"
    txn = PublicationTransaction(root)
    ref, sha = txn.write_record("checkpoints", filename, payload=checkpoint.payload)
    if host_facts:
        txn.write_record(
            "checkpoints",
            f"host-facts-{checkpoint.digest[:16]}.json",
            payload={
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "kind": "host_checkpoint_facts",
                "checkpoint_ref": ref,
                "checkpoint_sha256": sha,
                "facts": json_safe(host_facts),
                "recorded_at_epoch": time.time(),
            },
        )
    if owner:
        node_id = f"checkpoint:{safe_identifier(checkpoint.digest[:16])}"
        txn.write_record(
            "nodes",
            f"{node_id}.json",
            payload={
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "node_id": node_id,
                "kind": "checkpoint",
                "parent_ids": list(parent_ids),
                "owner": dict(owner),
                "content_ref": ref,
                "content_sha256": sha,
                "checkpoint_ref": ref,
            },
        )
    txn.commit()
    register_portable_capture_file(
        root / "checkpoints" / filename,
        artifacts_dir,
        label="authored continuation checkpoint",
    )
    return ref


def _optional_text_or_list(value: Any) -> str | list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    raise AuthoredCheckpointError(
        "checkpoint fields must be strings or lists of strings"
    )


def _iter_string_values(value: Any) -> Sequence[str]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _author_attribution(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        actor_kind = required_text(value.get("actor_kind"), "user")
        actor_id = required_text(
            value.get("actor_id"),
            os.environ.get("SASE_AGENT_NAME") or "user",
        )
        return {"actor_kind": actor_kind, "actor_id": actor_id}
    actor_id = (
        value
        if isinstance(value, str) and value
        else os.environ.get("SASE_AGENT_NAME") or "user"
    )
    return {"actor_kind": "user", "actor_id": str(actor_id)}


__all__ = [
    "AuthoredCheckpoint",
    "AuthoredCheckpointError",
    "MAX_CHECKPOINT_BYTES",
    "canonicalize_authored_checkpoint",
    "load_authored_checkpoint",
    "persist_authored_checkpoint",
    "publish_handoff_checkpoint",
    "publish_handoff_checkpoint_best_effort",
]
