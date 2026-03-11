"""Filesystem queue operations for the spec writer."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse

_BASE_DIR = Path.home() / ".sase" / "spec_writer"


def _get_requests_dir() -> Path:
    return _BASE_DIR / "requests"


def _get_responses_dir() -> Path:
    return _BASE_DIR / "responses"


def _get_completed_keys_dir() -> Path:
    return _BASE_DIR / "completed_keys"


def ensure_queue_dirs() -> None:
    """Create all queue directories if they don't exist."""
    for fn in (_get_requests_dir, _get_responses_dir, _get_completed_keys_dir):
        fn().mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via tempfile + os.replace()."""
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, str(path))
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def enqueue_request(request: SpecWriteRequest) -> Path:
    """Write a request to the requests directory. Returns the file path."""
    path = _get_requests_dir() / f"{request.request_id}.json"
    _atomic_write_json(path, request.to_dict())
    return path


def dequeue_pending() -> list[SpecWriteRequest]:
    """Read all pending requests, sorted by timestamp."""
    requests_dir = _get_requests_dir()
    if not requests_dir.exists():
        return []
    results = []
    for p in requests_dir.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            results.append(SpecWriteRequest.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    results.sort(key=lambda r: r.timestamp)
    return results


def write_response(response: SpecWriteResponse) -> Path:
    """Write a response to the responses directory. Returns the file path."""
    path = _get_responses_dir() / f"{response.request_id}.json"
    _atomic_write_json(path, response.to_dict())
    return path


def read_response(request_id: str) -> SpecWriteResponse | None:
    """Read a response by request_id. Returns None if not found."""
    path = _get_responses_dir() / f"{request_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return SpecWriteResponse.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def delete_response(request_id: str) -> None:
    """Delete a response file."""
    path = _get_responses_dir() / f"{request_id}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def delete_request(request_id: str) -> None:
    """Delete a request file."""
    path = _get_requests_dir() / f"{request_id}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# --- Idempotency ---


def _hash_idempotency_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def write_completed_key(key: str) -> None:
    """Record that a request with this idempotency key has been completed."""
    hashed = _hash_idempotency_key(key)
    path = _get_completed_keys_dir() / f"{hashed}.key"
    path.write_text(str(time.time()))


def has_completed_key(key: str) -> bool:
    """Check if a request with this idempotency key has already been completed."""
    hashed = _hash_idempotency_key(key)
    path = _get_completed_keys_dir() / f"{hashed}.key"
    return path.exists()


def find_pending_by_idempotency_key(key: str) -> SpecWriteRequest | None:
    """Find a pending request with the given idempotency key."""
    for req in dequeue_pending():
        if req.idempotency_key == key:
            return req
    return None


# --- Cleanup ---


def reap_completed_keys(ttl: float = 120.0) -> int:
    """Remove completed key markers older than ttl seconds. Returns count removed."""
    keys_dir = _get_completed_keys_dir()
    if not keys_dir.exists():
        return 0
    now = time.time()
    removed = 0
    for p in keys_dir.glob("*.key"):
        try:
            ts = float(p.read_text().strip())
            if now - ts > ttl:
                p.unlink()
                removed += 1
        except (OSError, ValueError):
            pass
    return removed


def cleanup_stale(request_ttl: float = 60.0, response_ttl: float = 120.0) -> None:
    """Remove stale request and response files older than their TTLs."""
    now = time.time()
    for directory, ttl in [
        (_get_requests_dir(), request_ttl),
        (_get_responses_dir(), response_ttl),
    ]:
        if not directory.exists():
            continue
        for p in directory.glob("*.json"):
            try:
                if now - p.stat().st_mtime > ttl:
                    p.unlink()
            except OSError:
                pass
