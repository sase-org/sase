"""Shared storage, reference, and JSON helpers for continuation capture."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import uuid

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

from ._constants import CAPTURE_ERRORS_FILENAME, CONTINUATION_DIRNAME

_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
JOURNAL_FILENAME = ".publication_journal.json"


class _PublicationConflictError(ValueError):
    """An immutable capture path already exists with different content."""


class _PublicationIncompleteError(RuntimeError):
    """A multi-file capture publication did not finish successfully."""


def record_capture_error(
    artifacts_dir: str | os.PathLike[str] | None,
    stage: str,
    exc: BaseException,
) -> None:
    """Append a continuation capture error without affecting caller behavior."""

    if artifacts_dir is None:
        return
    try:
        root = continuation_root(artifacts_dir)
        root.mkdir(parents=True, exist_ok=True)
        with (root / CAPTURE_ERRORS_FILENAME).open("a", encoding="utf-8") as stream:
            json.dump(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "recorded_at_epoch": time.time(),
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
    except OSError:
        pass


def write_text_blob(root: Path, text: str) -> tuple[str, Path, str, int]:
    data = text.encode("utf-8")
    digest = _sha_bytes(data)
    path = root / "text" / f"{digest}.txt"
    _write_immutable_bytes(path, data)
    return local_ref("text", f"{digest}.txt"), path, digest, len(data)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_bytes(payload)
    _write_pointer_bytes(path, data)
    return _sha_bytes(data)


def _write_immutable_bytes(path: Path, data: bytes) -> str:
    digest = _sha_bytes(data)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise _PublicationIncompleteError(
                f"could not read existing capture file {path}: {exc}"
            ) from exc
        if existing == data:
            return digest
        raise _PublicationConflictError(
            f"conflicting continuation write at {path}: "
            f"existing sha256 {_sha_bytes(existing)} != {_sha_bytes(data)}"
        )
    _write_bytes_atomic(path, data)
    return digest


def _write_pointer_bytes(path: Path, data: bytes) -> str:
    _write_bytes_atomic(path, data)
    return _sha_bytes(data)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def recover_publication_journal(root: Path) -> bool:
    """Finish or abort a leftover multi-file publication journal.

    Returns True when the leftover journal described a complete, matching
    publication. Incomplete journals drop their pointer files so callers
    cannot observe a successful publish of missing content.
    """

    journal_path = root / JOURNAL_FILENAME
    payload = read_json_object(journal_path)
    if not payload:
        return False
    if _journal_files_match(root, payload):
        _unlink_if_exists(journal_path)
        return True
    for entry in payload.get("pointers") or []:
        relpath = entry.get("relpath") if isinstance(entry, Mapping) else None
        if isinstance(relpath, str) and relpath:
            _unlink_if_exists(root / relpath)
    _unlink_if_exists(journal_path)
    return False


def _journal_files_match(root: Path, payload: Mapping[str, Any]) -> bool:
    for group in ("blobs", "records", "pointers"):
        raw_entries = payload.get(group)
        if not isinstance(raw_entries, list):
            continue
        for entry in raw_entries:
            if not isinstance(entry, Mapping):
                return False
            relpath = entry.get("relpath")
            digest = entry.get("sha256")
            if not isinstance(relpath, str) or not isinstance(digest, str):
                return False
            path = root / relpath
            try:
                existing = path.read_bytes()
            except OSError:
                return False
            if _sha_bytes(existing) != digest:
                return False
    return True


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _journal_entry(root: Path, path: Path, data: bytes) -> dict[str, str]:
    return {
        "relpath": str(path.relative_to(root)),
        "sha256": _sha_bytes(data),
    }


@dataclass
class PublicationTransaction:
    """Persist blobs, then records, then pointers, with a recoverable journal."""

    root: Path
    publication_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _blobs: list[tuple[Path, bytes]] = field(default_factory=list)
    _records: list[tuple[Path, bytes]] = field(default_factory=list)
    _pointers: list[tuple[Path, bytes]] = field(default_factory=list)

    def write_text_blob(self, text: str) -> tuple[str, Path, str, int]:
        data = text.encode("utf-8")
        digest = _sha_bytes(data)
        path = self.root / "text" / f"{digest}.txt"
        self._blobs.append((path, data))
        return local_ref("text", f"{digest}.txt"), path, digest, len(data)

    def write_record(
        self,
        *relpath_parts: str,
        payload: Mapping[str, Any],
    ) -> tuple[str, str]:
        data = _json_bytes(payload)
        path = self.root.joinpath(*relpath_parts)
        self._records.append((path, data))
        return local_ref(*relpath_parts), _sha_bytes(data)

    def write_pointer(
        self,
        *relpath_parts: str,
        payload: Mapping[str, Any],
    ) -> tuple[str, str]:
        data = _json_bytes(payload)
        path = self.root.joinpath(*relpath_parts)
        self._pointers.append((path, data))
        return local_ref(*relpath_parts), _sha_bytes(data)

    def commit(self) -> None:
        recover_publication_journal(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        journal_path = self.root / JOURNAL_FILENAME
        listed: dict[str, Any] = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "publication_id": self.publication_id,
            "stage": "pending",
            "blobs": [
                _journal_entry(self.root, path, data) for path, data in self._blobs
            ],
            "records": [
                _journal_entry(self.root, path, data) for path, data in self._records
            ],
            "pointers": [
                _journal_entry(self.root, path, data) for path, data in self._pointers
            ],
            "recorded_at_epoch": time.time(),
        }
        try:
            _write_pointer_bytes(journal_path, _json_bytes(listed))
            for path, data in self._blobs:
                _write_immutable_bytes(path, data)
            listed["stage"] = "blobs"
            _write_pointer_bytes(journal_path, _json_bytes(listed))
            for path, data in self._records:
                _write_immutable_bytes(path, data)
            listed["stage"] = "records"
            _write_pointer_bytes(journal_path, _json_bytes(listed))
            for path, data in self._pointers:
                _write_pointer_bytes(path, data)
            listed["stage"] = "complete"
            _write_pointer_bytes(journal_path, _json_bytes(listed))
            _unlink_if_exists(journal_path)
        except Exception:
            if recover_publication_journal(self.root):
                return
            raise


def register_portable_capture_file(
    path: Path,
    artifacts_dir: str | os.PathLike[str],
    *,
    label: str,
) -> str | None:
    """Best-effort explicit artifact snapshot for retention protection."""

    try:
        from sase.core.artifact_file_facade import store_explicit_artifact_file

        artifact = store_explicit_artifact_file(
            path,
            str(artifacts_dir),
            label=label,
            kind="file",
        )
    except Exception:
        return None
    return f"file:{artifact.id}"


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [json_safe(item) for item in value]
    return str(value)


def continuation_root(artifacts_dir: str | os.PathLike[str]) -> Path:
    return Path(artifacts_dir) / CONTINUATION_DIRNAME


def local_ref(*parts: str) -> str:
    return "local:" + "/".join((CONTINUATION_DIRNAME, *parts))


def sha_text(text: str) -> str:
    return _sha_bytes(text.encode("utf-8"))


def sha_json(payload: Mapping[str, Any]) -> str:
    return _sha_bytes(_json_bytes(payload))


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_ref(kind: str, label: str, seed: str) -> str:
    safe_kind = safe_identifier(kind, max_len=40)
    safe_label = safe_identifier(label or "unknown", max_len=56)
    return f"{safe_kind}:{safe_label}:{sha_text(seed)[:16]}"


def wire_reference_or_none(value: str | None) -> str | None:
    if not value:
        return None
    return wire_reference(value, fallback_kind="source")


def wire_reference(value: str, *, fallback_kind: str) -> str:
    if not value:
        return f"{fallback_kind}:empty"
    if len(value.encode("utf-8")) <= 1024 and not any(ch.isspace() for ch in value):
        return value
    return f"{fallback_kind}:{sha_text(value)[:16]}"


def safe_identifier(value: object, *, max_len: int = 80) -> str:
    text = str(value).strip() or "unknown"
    text = _ID_SAFE_RE.sub("_", text)
    text = text.strip("_.:-") or "unknown"
    if len(text.encode("utf-8")) <= max_len:
        return text
    digest = sha_text(text)[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{text[:keep]}:{digest}"


def unique_refs(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw:
            continue
        ref = wire_reference(raw, fallback_kind="ref")
        if ref in seen:
            continue
        seen.add(ref)
        result.append(ref)
    return result


def unique_identifiers(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw:
            continue
        identifier = wire_reference(raw, fallback_kind="id")
        if len(identifier.encode("utf-8")) > 256:
            identifier = f"id:{sha_text(identifier)[:16]}"
        if identifier in seen:
            continue
        seen.add(identifier)
        result.append(identifier)
    return result


def iter_string_list(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        return (item for item in value if isinstance(item, str) and item)
    return ()


def required_text(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def update_agent_meta_fields(
    artifacts_dir: str | os.PathLike[str],
    fields: Mapping[str, Any],
) -> None:
    try:
        from sase.axe.run_agent_helpers import update_meta_fields

        update_meta_fields(str(artifacts_dir), dict(fields))
    except Exception:
        pass
