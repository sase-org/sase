"""Shared git and filesystem helpers for stale-replay recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import loads
from pathlib import Path

from sase.agents_sync.git import GitBytesRunner, GitRunner
from sase.agents_sync.git_sync_ops import agents_git_error
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_models import V2RunRecord
from sase.agents_sync.v2_snapshot_io import decode_hood_snapshot
from sase.core.agent_identity_facade import AgentOwnerIdentity


@dataclass(frozen=True, slots=True)
class ReplayBaseRun:
    """One merge-base run and the bytes referenced by its owner snapshot."""

    record: V2RunRecord
    payloads: dict[str, bytes]


def git_text(repo: Path, git_runner: GitRunner, args: list[str], op: str) -> str:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        raise AgentsSyncFormatError(
            agents_git_error(f"git {' '.join(args)} failed", result)
        )
    return result.stdout.strip()


def file_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def git_optional_bytes(
    repo: Path, git_runner: GitBytesRunner, args: list[str], op: str
) -> bytes | None:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        return None
    return result.stdout


def _git_blob_bytes(
    repo: Path,
    git_runner: GitBytesRunner,
    revision: str,
    relative: str,
    op: str,
) -> bytes | None:
    return git_optional_bytes(repo, git_runner, ["show", f"{revision}:{relative}"], op)


def replay_value_bytes(value: object) -> bytes:
    """Encode replayable JSON metadata deterministically for the core policy."""

    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def replay_run_field(run: object, field: str) -> object:
    value = getattr(run, field)
    if field == "metadata":
        return dict(value)
    if field == "commits":
        return [item.to_json_dict() for item in value]
    return value


def read_merge_base_runs(
    repo: Path,
    owner: AgentOwnerIdentity,
    hoods: tuple[str, ...],
    merge_base: str | None,
    git_runner: GitBytesRunner,
) -> dict[str, ReplayBaseRun]:
    """Read same-run fields and payloads from the recorded merge-base."""

    if merge_base is None:
        return {}
    runs: dict[str, ReplayBaseRun] = {}
    for hood in hoods:
        snapshot_bytes = _git_blob_bytes(
            repo,
            git_runner,
            merge_base,
            snapshot_path(owner, hood),
            "replay_merge_base_snapshot",
        )
        if snapshot_bytes is None:
            continue
        try:
            snapshot = decode_hood_snapshot(loads(snapshot_bytes.decode()))
        except (UnicodeDecodeError, AgentsSyncFormatError, ValueError):
            continue
        for record in snapshot.runs:
            payloads: dict[str, bytes] = {}
            for kind, reference in record.files:
                content = _git_blob_bytes(
                    repo,
                    git_runner,
                    merge_base,
                    reference.path,
                    "replay_merge_base_payload",
                )
                if content is not None:
                    payloads[kind] = content
            runs[record.global_name] = ReplayBaseRun(record, payloads)
    return runs
