"""Daemon-backed ChangeSpec project-file write helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.core.rust import require_rust_binding
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_wire_from_dict
from sase.daemon.client import LocalDaemonClient
from sase.daemon.write_facade import DaemonWriteResult, write_or_fallback

MUTATION_WIRE_SCHEMA_VERSION = 1
SOURCE_EXPORT_KIND_PROJECT_FILE = "project_file"


def write_changespec_project_file_mutation[T](
    surface: str,
    *,
    project_file: str,
    changespec_name: str,
    updated_content: str,
    payload: dict[str, Any],
    commit_message: str,
    return_value: T,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[T]:
    """Route one ChangeSpec source-file rewrite through daemon or fallback."""

    with changespec_lock(project_file):
        return write_changespec_project_file_mutation_locked(
            surface,
            project_file=project_file,
            changespec_name=changespec_name,
            updated_content=updated_content,
            payload=payload,
            commit_message=commit_message,
            return_value=return_value,
            args=args,
            client=client,
        )


def write_changespec_project_file_mutation_locked[T](
    surface: str,
    *,
    project_file: str,
    changespec_name: str,
    updated_content: str,
    payload: dict[str, Any],
    commit_message: str,
    return_value: T,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[T]:
    """Same as above, but the caller already holds ``changespec_lock``."""

    with open(project_file, encoding="utf-8") as f:
        current_content = f.read()
    if current_content == updated_content:
        return DaemonWriteResult(
            value=return_value,
            surface=surface,
            used_daemon=False,
            fallback_reason="unchanged",
            fallback_message="project file content is already current",
        )

    expected = _source_fingerprint(project_file, current_content)
    spec = _changespec_spec_from_content(project_file, updated_content, changespec_name)
    request_payload = {
        **payload,
        "spec": spec,
        "is_archive": _is_archive_project_file(project_file),
    }
    export_plan = _source_export_plan(
        project_file,
        expected_fingerprint=expected,
        content_utf8=updated_content,
        repair_context={
            "domain": "changespec",
            "changespec_name": changespec_name,
            "surface": surface,
        },
    )
    write_data = {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "project_id": _project_id(project_file),
        "idempotency_key": _idempotency_key(
            surface,
            project_file,
            changespec_name,
            expected,
            request_payload,
            export_plan["content_sha256"],
        ),
        "actor": _actor(),
        "payload": request_payload,
        "expected_source_fingerprints": [expected],
        "source_exports": [export_plan],
    }

    def daemon_writer(daemon: LocalDaemonClient) -> T:
        daemon.write(surface, write_data)
        return return_value

    def direct_writer() -> T:
        write_changespec_atomic(project_file, updated_content, commit_message)
        return return_value

    return write_or_fallback(
        surface,
        daemon_writer=daemon_writer,
        direct_writer=direct_writer,
        args=args,
        client=client,
        required_capability="changespecs.write",
    )


def _changespec_spec_from_content(
    project_file: str, content: str, changespec_name: str
) -> dict[str, Any]:
    rust_parse_project_bytes = require_rust_binding("parse_project_bytes")
    raw_specs: list[dict[str, Any]] = rust_parse_project_bytes(
        project_file, content.encode("utf-8")
    )
    specs = [changespec_wire_from_dict(record) for record in raw_specs]
    for spec in specs:
        if spec.name == changespec_name:
            return to_json_dict(spec)
    raise ValueError(f"ChangeSpec {changespec_name!r} not found after update")


def _source_fingerprint(path: str, content: str) -> dict[str, Any]:
    encoded = content.encode("utf-8")
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "file_size": len(encoded),
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _source_export_plan(
    path: str,
    *,
    expected_fingerprint: dict[str, Any],
    content_utf8: str,
    repair_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "target_path": path,
        "kind": SOURCE_EXPORT_KIND_PROJECT_FILE,
        "expected_fingerprint": expected_fingerprint,
        "content_sha256": hashlib.sha256(content_utf8.encode("utf-8")).hexdigest(),
        "content_utf8": content_utf8,
        "repair_context": repair_context,
    }


def _idempotency_key(
    surface: str,
    project_file: str,
    changespec_name: str,
    expected_fingerprint: dict[str, Any],
    payload: dict[str, Any],
    content_sha256: str,
) -> str:
    stable = {
        "surface": surface,
        "project_file": str(Path(project_file).expanduser()),
        "changespec_name": changespec_name,
        "expected_fingerprint": expected_fingerprint,
        "payload": payload,
        "content_sha256": content_sha256,
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"changespec:{surface}:{hashlib.sha256(encoded).hexdigest()}"


def _actor() -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "actor_type": "python",
        "name": "sase-cli",
    }


def _project_id(project_file: str) -> str:
    return Path(project_file).expanduser().parent.name


def _is_archive_project_file(project_file: str) -> bool:
    return Path(project_file).name.endswith("-archive.sase") or Path(
        project_file
    ).name.endswith("-archive.gp")


__all__ = [
    "write_changespec_project_file_mutation",
    "write_changespec_project_file_mutation_locked",
]
