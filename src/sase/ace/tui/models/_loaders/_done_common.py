"""Shared helpers for completed-agent loaders."""

from pathlib import Path
from typing import Any

from sase.ace.revert_agent import agent_is_reverted

from ..agent import Agent


def enrich_agent_revert_state(agent: Agent, artifact_dir: str | Path | None) -> None:
    agent.reverted = agent_is_reverted(str(artifact_dir) if artifact_dir else None)


def single_commit_record_from_metadata(
    metadata: dict[str, str],
) -> dict[str, str] | None:
    record: dict[str, str] = {}
    if message := metadata.get("meta_commit_message"):
        record["message"] = message
    if sha := metadata.get("meta_new_commit"):
        record["sha"] = sha
    if cwd := metadata.get("meta_commit_cwd"):
        record["cwd"] = cwd
    if committed_at := metadata.get("meta_commit_committed_at"):
        record["committed_at"] = committed_at
    return record or None


def commit_results_marker_exists(artifact_dir: str | Path | None) -> bool:
    if artifact_dir is None:
        return False
    return (Path(artifact_dir).expanduser() / "commit_results.json").is_file()


def commit_record_key(record: dict[str, Any]) -> tuple[str, str] | None:
    cwd = record.get("cwd")
    sha = record.get("sha") or record.get("result") or record.get("commit_result")
    cwd_text = cwd if isinstance(cwd, str) else ""
    sha_text = sha if isinstance(sha, str) else ""
    if not cwd_text and not sha_text:
        return None
    return (cwd_text, sha_text)


def merge_commit_records(
    existing_records: list[object],
    loaded_records: list[dict[str, str]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for raw_record in [*existing_records, *loaded_records]:
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        key = commit_record_key(record)
        if key is not None and key in index_by_key:
            merged[index_by_key[key]].update(record)
            continue
        if key is not None:
            index_by_key[key] = len(merged)
        merged.append(record)
    return merged


def enrich_missing_commit_metadata(
    agent: Agent, artifact_dir: str | Path | None
) -> None:
    """Backfill and merge commit cwd/list metadata for done markers."""
    from sase.axe.run_agent_helpers_state import (
        read_commit_result_metadata,
        read_commit_results_metadata,
    )

    step_output = agent.step_output
    marker_exists = commit_results_marker_exists(artifact_dir)
    artifact_dir_str = str(artifact_dir) if artifact_dir else None
    commits = read_commit_results_metadata(artifact_dir_str) if marker_exists else []
    if not isinstance(step_output, dict):
        if not commits:
            return
        step_output = {}
        agent.step_output = step_output

    has_primary_commit = bool(
        step_output.get("meta_commit_message") or step_output.get("meta_new_commit")
    )
    existing_raw = step_output.get("meta_commits")
    existing_commits = existing_raw if isinstance(existing_raw, list) else []

    if not (has_primary_commit or existing_commits or marker_exists):
        return

    single_metadata: dict[str, str] | None = None

    if not commits and has_primary_commit and not existing_commits:
        single_metadata = read_commit_result_metadata(artifact_dir_str)
        single_commit = single_commit_record_from_metadata(single_metadata)
        commits = [single_commit] if single_commit else []
    if existing_commits or commits:
        merged_commits = merge_commit_records(existing_commits, commits)
        if merged_commits:
            step_output["meta_commits"] = merged_commits

    if has_primary_commit and not step_output.get("meta_commit_cwd"):
        if single_metadata is None:
            single_metadata = read_commit_result_metadata(artifact_dir_str)
        commit_cwd = single_metadata.get("meta_commit_cwd")
        if commit_cwd:
            step_output["meta_commit_cwd"] = commit_cwd


def done_extra_files(
    plan_path: str | None,
    markdown_pdf_paths: object,
    image_paths: object,
    video_paths: object,
) -> list[str]:
    """Return plan/PDF/image/video attachments for the Agents tab file panel."""
    files: list[str] = []
    seen: set[str] = set()
    markdown_pdfs = markdown_pdf_paths if isinstance(markdown_pdf_paths, list) else []
    images = image_paths if isinstance(image_paths, list) else []
    videos = video_paths if isinstance(video_paths, list) else []
    for path in [plan_path, *markdown_pdfs, *images, *videos]:
        if not isinstance(path, str):
            continue
        if not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files
