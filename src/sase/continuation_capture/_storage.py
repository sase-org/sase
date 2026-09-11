"""Shared storage, reference, and JSON helpers for continuation capture."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

from ._constants import CAPTURE_ERRORS_FILENAME, CONTINUATION_DIRNAME

_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


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
    if not path.exists():
        _write_bytes_atomic(path, data)
    return local_ref("text", f"{digest}.txt"), path, digest, len(data)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_bytes(payload)
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
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


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
