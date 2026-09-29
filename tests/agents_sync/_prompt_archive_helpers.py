"""Shared builders for prompt-archive tests."""

from __future__ import annotations

from pathlib import Path

import sase_core_rs


class HostedLinks:
    def agent_url(self, name: str) -> str:
        return f"https://example.test/agents/{name}"

    def plan_url(self, plan_ref: str) -> str:
        label = plan_ref.removeprefix("plan:").removeprefix("plans:")
        return f"https://example.test/plans/{label}"

    def blob_url_for_repository(
        self,
        _root: Path,
        revision: str,
        path: str,
    ) -> str:
        return f"https://example.test/blob/{revision}/{path}"

    def commit_url_for_repository(self, _root: Path, sha: str) -> str:
        return f"https://example.test/commit/{sha}"

    def bead_url(self, bead_id: str) -> str:
        return f"https://example.test/beads/{bead_id}"


def make_record(
    *,
    artifacts_dir: Path,
    raw_ref: str,
    label: str,
    sha256: str | None = None,
    pool_relpath: str | None = None,
    vcs_repo: str | None = None,
    vcs_relpath: str | None = None,
    vcs_revision: str | None = None,
    ref_kind: str = "file",
    locator: str | None = None,
) -> dict[str, object]:
    object_relpath = (
        None if sha256 is None else sase_core_rs.artifact_object_relpath(sha256)
    )
    return {
        "schema_version": sase_core_rs.prompt_artifact_wire_schema_version(),
        "recorded_at": "2026-08-01T14:22:03Z",
        "agent_artifacts_dir": str(artifacts_dir),
        "raw_ref": raw_ref,
        "expanded_ref": raw_ref,
        "ref_kind": ref_kind,
        "label": label,
        "source_path": None,
        "sha256": sha256,
        "size_bytes": None,
        "mime_type": None,
        "pool_relpath": pool_relpath,
        "vcs_repo": vcs_repo,
        "vcs_relpath": vcs_relpath,
        "vcs_revision": vcs_revision,
        "locator": locator,
        "skipped_reason": None,
        "logical_path": None,
        "root_name": None,
        "authored_path": None,
        "origin": None,
        "object_relpath": object_relpath,
        "sidecar_visibility": None,
    }


def write_manifest(workspace: Path, rows: list[dict[str, object]]) -> None:
    path = workspace / ".sase/artifacts/prompt-artifacts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"{sase_core_rs.prompt_artifact_manifest_render_record(row)}\n"
            for row in rows
        ),
        encoding="utf-8",
    )
