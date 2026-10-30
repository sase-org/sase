"""Capture a resolved ``@file:<path>`` reference into the local artifact pool.

Split out of :mod:`sase.core.prompt_artifact_staging` to keep each module
under the 500-line cap. Staging lives in
:mod:`sase.core.prompt_artifact_staging_stage`; pool IO lives in
:mod:`sase.core.prompt_artifact_staging_pool`. The public import path
remains :mod:`sase.core.prompt_artifact_staging`.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import tempfile

from sase.core._prompt_artifact_staging_shared import (
    PROMPT_ARTIFACT_MANIFEST_LOCK_NAME,
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PROMPT_ARTIFACT_POOL_DIR,
    PromptArtifactRecord,
    agents_sidecar_metadata,
    base_record,
    resolve_agent_artifacts_dir,
)
from sase.core.artifact_capture_policy import capture_file_exceeds_size_limit
from sase.core.artifact_file_helpers import artifact_file_mime_type
from sase.core.prompt_artifact_staging_pool import (
    append_manifest_record,
    pool_exceeds_budget,
    prune_prompt_artifact_pool,
    store_captured_tmp_and_append_record,
)
from sase.core.rust import require_rust_binding


log = logging.getLogger(__name__)


def capture_prompt_file_ref(
    *,
    source: Path,
    logical_path: str,
    root_name: str,
    authored_path: str,
    raw_ref: str,
    expanded_ref: str,
    workspace_root: Path | str | None = None,
    agent_artifacts_dir: Path | str | None = None,
) -> PromptArtifactRecord | None:
    """Capture one resolved ``@file:<path>`` reference into the local pool.

    The pool stem stays fixed at ``file-ref`` so local basenames remain only in
    manifest metadata, but the source suffix is mirrored into the pool filename.
    That makes local pool deduplication per digest and suffix; the durable object
    path remains digest-addressed through ``object_relpath``.
    """

    try:
        artifacts_dir = resolve_agent_artifacts_dir(agent_artifacts_dir)
        if artifacts_dir is None:
            return None
        workspace = (
            Path(workspace_root or Path.cwd()).expanduser().resolve(strict=False)
        )
        staging_root = workspace / ".sase" / "artifacts"
        manifest_path = staging_root / PROMPT_ARTIFACT_MANIFEST_NAME
        lock_path = staging_root / PROMPT_ARTIFACT_MANIFEST_LOCK_NAME
        source = Path(source).expanduser().resolve(strict=True)
        record = base_record(
            raw_ref=raw_ref,
            expanded_ref=expanded_ref,
            ref_kind="file",
            label=source.name,
            locator=logical_path,
            agent_artifacts_dir=artifacts_dir,
        )
        record["source_path"] = str(source)
        record["logical_path"] = logical_path
        record["root_name"] = root_name
        record["authored_path"] = authored_path
        record["origin"] = "ref"
        _repo, visibility = agents_sidecar_metadata(workspace)
        record["sidecar_visibility"] = visibility

        pool_dir = staging_root / PROMPT_ARTIFACT_POOL_DIR
        pool_dir.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_name = tempfile.mkstemp(
            prefix=".capture.",
            suffix=".tmp",
            dir=pool_dir,
        )
        os.close(descriptor)
        tmp_path = Path(tmp_name)
        try:
            digest = hashlib.sha256()
            size_bytes = 0
            with source.open("rb") as input_stream, tmp_path.open("wb") as output:
                while chunk := input_stream.read(1024 * 1024):
                    size_bytes += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            sha256 = digest.hexdigest()
            record["sha256"] = sha256
            record["size_bytes"] = size_bytes
            record["mime_type"] = artifact_file_mime_type(source)
            record["object_relpath"] = str(
                require_rust_binding("artifact_object_relpath")(sha256)
            )
            if capture_file_exceeds_size_limit(size_bytes):
                record["skipped_reason"] = "too-large"
                append_manifest_record(manifest_path, lock_path, record)
                return record

            # Keep the user's basename out of the pool path, but preserve the
            # suffix so downstream readers can infer the captured file type.
            pool_filename = str(
                require_rust_binding("prompt_artifact_pool_filename")(
                    sha256,
                    f"file-ref{source.suffix}",
                )
            )
            pool_relpath = f"{PROMPT_ARTIFACT_POOL_DIR}/{pool_filename}"
            record["pool_relpath"] = pool_relpath
            pool_path = staging_root / pool_relpath
            created = store_captured_tmp_and_append_record(
                tmp_path=tmp_path,
                expected_sha256=sha256,
                pool_path=pool_path,
                manifest_path=manifest_path,
                lock_path=lock_path,
                record=record,
            )
            if created and pool_exceeds_budget(staging_root):
                prune_prompt_artifact_pool(workspace)
            return record
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - capture is launch auxiliary work.
        log.debug(
            "Could not capture prompt file ref %s: %s", raw_ref, exc, exc_info=True
        )
        return None


__all__ = [
    "capture_prompt_file_ref",
]
