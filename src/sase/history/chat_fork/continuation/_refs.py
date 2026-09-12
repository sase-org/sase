"""Resolve local and portable continuation content refs with digest checks."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..common import load_json_object
from ._util import ContinuationSourceError, sha_json

_LOCAL_PREFIX = "local:continuation/"
_FILE_PREFIX = "file:"


def continuation_ref_path(artifact_dir: Path, ref: str) -> Path | None:
    """Return the on-disk path for *ref* relative to *artifact_dir*, if local."""

    if not ref:
        return None
    if ref.startswith(_LOCAL_PREFIX):
        root = (artifact_dir / "continuation").resolve(strict=False)
        path = (root / ref.removeprefix(_LOCAL_PREFIX)).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path
    if ref.startswith(_FILE_PREFIX):
        return _portable_file_ref_path(ref)
    return None


def read_json_ref(
    artifact_dir: Path,
    ref: str,
    *,
    expected_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Load a JSON continuation ref and optionally verify its digest."""

    path = continuation_ref_path(artifact_dir, ref)
    if path is None:
        raise ContinuationSourceError(
            "missing_source",
            f"could not resolve continuation ref {ref}",
        )
    payload = load_json_object(path)
    if not payload:
        raise ContinuationSourceError(
            "missing_source",
            f"continuation ref {ref} is missing or not a JSON object",
        )
    _check_digest(payload, expected_sha256, ref)
    return payload


def read_text_ref(
    artifact_dir: Path,
    ref: str,
    *,
    expected_sha256: str | None = None,
) -> str:
    """Load a text continuation ref and optionally verify its digest."""

    path = continuation_ref_path(artifact_dir, ref)
    if path is None:
        raise ContinuationSourceError(
            "missing_source",
            f"could not resolve continuation text ref {ref}",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContinuationSourceError(
            "missing_source",
            f"could not read continuation text ref {ref}: {exc}",
        ) from exc
    if expected_sha256:
        digest = _sha_text(text)
        if digest != expected_sha256:
            raise ContinuationSourceError(
                "digest_mismatch",
                f"digest mismatch for {ref}: expected {expected_sha256}, got {digest}",
            )
    return text


def _check_digest(
    payload: Mapping[str, Any],
    expected_sha256: str | None,
    ref: str,
) -> None:
    if not expected_sha256:
        return
    digest = sha_json(payload)
    if digest != expected_sha256:
        raise ContinuationSourceError(
            "digest_mismatch",
            f"digest mismatch for {ref}: expected {expected_sha256}, got {digest}",
        )


def _portable_file_ref_path(ref: str) -> Path | None:
    artifact_id = ref.removeprefix(_FILE_PREFIX)
    if artifact_id.startswith("explicit:"):
        artifact_id = artifact_id.removeprefix("explicit:")
    if not artifact_id:
        return None
    try:
        from sase.core.artifact_file_facade import read_artifact_file_index
    except Exception:
        return None
    try:
        rows = read_artifact_file_index()
    except Exception:
        return None
    for row in rows:
        if row.id == artifact_id or row.id.endswith(artifact_id):
            if row.path:
                return Path(row.path).expanduser()
    return None


def _sha_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
