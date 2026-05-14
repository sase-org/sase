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


def write_changespec_archive_move_mutation_locked(
    *,
    source_file: str,
    dest_file: str,
    changespec_name: str,
    source_content: str,
    dest_content: str,
    commit_message: str,
    return_value: bool,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[bool]:
    """Route an active/archive ChangeSpec move through one daemon mutation.

    The caller must already hold locks for ``source_file`` and ``dest_file`` in
    stable order.  Both rewritten project files are exported together so the
    daemon outbox can repair a crash between the add/remove filesystem writes.
    """

    current_source = _read_existing_text(source_file)
    current_dest = _read_existing_text(dest_file)
    if current_source == source_content and current_dest == dest_content:
        return DaemonWriteResult(
            value=return_value,
            surface="changespec.active_archive_moved",
            used_daemon=False,
            fallback_reason="unchanged",
            fallback_message="project file content is already current",
        )

    source_expected = _source_fingerprint(source_file, current_source)
    dest_expected = (
        _source_fingerprint(dest_file, current_dest)
        if current_dest is not None
        else None
    )
    spec = _changespec_spec_from_content(dest_file, dest_content, changespec_name)
    source_export = _source_export_plan(
        source_file,
        expected_fingerprint=source_expected,
        content_utf8=source_content,
        repair_context={
            "domain": "changespec",
            "changespec_name": changespec_name,
            "surface": "changespec.active_archive_moved",
            "role": "source",
        },
    )
    dest_export = _source_export_plan(
        dest_file,
        expected_fingerprint=dest_expected,
        content_utf8=dest_content,
        repair_context={
            "domain": "changespec",
            "changespec_name": changespec_name,
            "surface": "changespec.active_archive_moved",
            "role": "destination",
        },
    )
    source_exports = [source_export, dest_export]
    request_payload = {
        "spec": spec,
        "from_path": source_file,
        "to_path": dest_file,
        "is_archive": _is_archive_project_file(dest_file),
    }
    expected_fingerprints = [source_expected]
    if dest_expected is not None:
        expected_fingerprints.append(dest_expected)
    write_data = {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "project_id": _project_id(dest_file),
        "idempotency_key": _idempotency_key(
            "changespec.active_archive_moved",
            source_file,
            changespec_name,
            {"source": source_expected, "dest": dest_expected},
            request_payload,
            _source_exports_sha(source_exports),
        ),
        "actor": _actor(),
        "payload": request_payload,
        "expected_source_fingerprints": expected_fingerprints,
        "source_exports": source_exports,
    }

    def daemon_writer(daemon: LocalDaemonClient) -> bool:
        daemon.write("changespec.active_archive_moved", write_data)
        return return_value

    def direct_writer() -> bool:
        write_changespec_atomic(dest_file, dest_content, f"Add {changespec_name}")
        write_changespec_atomic(
            source_file, source_content, f"Remove {changespec_name}"
        )
        return return_value

    return write_or_fallback(
        "changespec.active_archive_moved",
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


def _source_fingerprint(path: str, content: str | None) -> dict[str, Any]:
    if content is None:
        raise FileNotFoundError(path)
    encoded = content.encode("utf-8")
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "file_size": len(encoded),
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _source_export_plan(
    path: str,
    *,
    expected_fingerprint: dict[str, Any] | None,
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


def _read_existing_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _source_exports_sha(exports: list[dict[str, Any]]) -> str:
    encoded = json.dumps(exports, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    "write_changespec_archive_move_mutation_locked",
    "write_changespec_project_file_mutation",
    "write_changespec_project_file_mutation_locked",
]
