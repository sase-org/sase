"""Inventory unpublished sidecar paths and write a verified backup."""

from __future__ import annotations

from hashlib import sha256
from json import loads
from pathlib import Path
import shutil
from typing import Any

from sase.agents_sync._publication_replay_recovery_support import (
    file_bytes,
    git_optional_bytes,
    git_text,
    read_merge_base_runs,
    replay_run_field,
    replay_value_bytes,
)
from sase.agents_sync._publication_replay_recovery_types import (
    BUNDLE_NAME,
    CHECKSUMS_NAME,
    COMPLETE_STAGE,
    MUTATION_STAGES,
    OBJECTS_DIR,
    PRESERVED_DIR,
    PROGRESS_NAME,
    REVISIONS_NAME,
    VERIFIED_STAGE,
    read_json,
    read_progress,
    write_progress,
)
from sase.agents_sync.git import GitBytesRunner, GitRunner
from sase.agents_sync.git_sync_ops import agents_ahead_count, agents_git_error
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_json
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.agents_sync.v2_snapshot_io import decode_hood_snapshot
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    REPLAY_BYTES_REFUSE,
    REPLAY_HOOD_ACTION_MERGE,
    ReplayByteDivergenceDecision,
    ReplayHoodMergeDecision,
    ReplayPathClassification,
    decide_replay_byte_divergence,
    decide_replay_hood_merge,
)


def observe_clone(repo: Path, git_runner: GitRunner) -> dict[str, Any]:
    head = git_text(repo, git_runner, ["rev-parse", "HEAD"], "replay_head")
    upstream = git_text(
        repo, git_runner, ["rev-parse", "@{upstream}"], "replay_upstream"
    )
    behind_result = git_runner(
        repo,
        ["rev-list", "--count", "HEAD..@{upstream}"],
        op="agents_sync.replay_behind",
    )
    try:
        behind = (
            int(behind_result.stdout.strip()) if behind_result.returncode == 0 else 0
        )
    except ValueError:
        behind = 0
    unpublished = _git_lines(
        repo,
        git_runner,
        ["rev-list", "--reverse", "@{upstream}..HEAD"],
        "replay_unpublished",
    )
    merge_base_result = git_runner(
        repo,
        ["merge-base", "HEAD", "@{upstream}"],
        op="agents_sync.replay_merge_base",
    )
    merge_base = (
        merge_base_result.stdout.strip()
        if merge_base_result.returncode == 0 and merge_base_result.stdout.strip()
        else None
    )
    return {
        "head": head,
        "upstream": upstream,
        "ahead": agents_ahead_count(repo, git_runner),
        "behind": behind,
        "unpublished": unpublished,
        "merge_base": merge_base,
    }


def collect_paths(repo: Path, git_runner: GitRunner) -> tuple[str, ...]:
    names: list[str] = []
    for args, op in (
        (["diff", "--name-only", "@{upstream}...HEAD"], "replay_commit_paths"),
        (["diff", "--name-only"], "replay_unstaged_paths"),
        (["diff", "--cached", "--name-only"], "replay_staged_paths"),
        (
            ["ls-files", "--others", "--exclude-standard"],
            "replay_untracked_paths",
        ),
    ):
        names.extend(_git_lines(repo, git_runner, args, op))
    return tuple(dict.fromkeys(names))


def ensure_backup(
    repo: Path,
    backup_root: Path,
    expected_head: str,
    observed: dict[str, Any],
    classified: ReplayPathClassification,
    hoods: tuple[str, ...],
    refused: tuple[str, ...],
    git_runner: GitRunner,
) -> None:
    existing = read_progress(backup_root)
    if existing is not None:
        if existing.get("expected_head") not in {expected_head, observed["head"]}:
            raise AgentsSyncFormatError(
                "backup directory belongs to a different HEAD; choose a new directory"
            )
        if existing.get("stage") in {
            VERIFIED_STAGE,
            *MUTATION_STAGES,
            COMPLETE_STAGE,
        }:
            return
    if observed["ahead"] > 0:
        bundle = backup_root / BUNDLE_NAME
        created = git_runner(
            repo,
            ["bundle", "create", str(bundle), "@{upstream}..HEAD"],
            op="agents_sync.replay_bundle",
        )
        if created.returncode != 0:
            raise AgentsSyncFormatError(
                agents_git_error("could not create unpublished bundle", created)
            )
        verified = git_runner(
            repo,
            ["bundle", "verify", str(bundle)],
            op="agents_sync.replay_bundle_verify",
        )
        if verified.returncode != 0:
            raise AgentsSyncFormatError(
                agents_git_error("unpublished bundle failed verification", verified)
            )
    preserved_root = backup_root / PRESERVED_DIR
    objects_root = backup_root / OBJECTS_DIR
    for relative in classified.owner_content:
        _copy_repo_file(repo, preserved_root, relative)
    for relative in classified.archive_object:
        _copy_repo_file(repo, objects_root, relative)
    atomic_write_json(
        backup_root / REVISIONS_NAME,
        {
            "head": observed["head"],
            "upstream": observed["upstream"],
            "merge_base": observed.get("merge_base"),
            "unpublished": list(observed["unpublished"]),
            "expected_head": expected_head,
        },
    )
    checksums = _checksum_tree(backup_root)
    atomic_write_json(backup_root / CHECKSUMS_NAME, checksums)
    write_progress(
        backup_root,
        {
            "schema_version": 1,
            "stage": VERIFIED_STAGE,
            "expected_head": expected_head,
            "observed_head": observed["head"],
            "upstream": observed["upstream"],
            "merge_base": observed.get("merge_base"),
            "unpublished": list(observed["unpublished"]),
            "hoods": list(hoods),
            "browsing": list(classified.browsing),
            "owner_content": list(classified.owner_content),
            "archive_object": list(classified.archive_object),
            "unknown": list(classified.unknown),
            "refused": list(refused),
        },
    )


def verify_backup(backup_root: Path) -> tuple[bool, str | None]:
    checksums_path = backup_root / CHECKSUMS_NAME
    if not checksums_path.is_file():
        return False, "backup checksums are missing"
    recorded = read_json(checksums_path)
    if not isinstance(recorded, dict):
        return False, "backup checksums are not an object"
    current = _checksum_tree(backup_root)
    for relative, digest in recorded.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            return False, "backup checksums are malformed"
        if relative in {PROGRESS_NAME, CHECKSUMS_NAME}:
            continue
        if current.get(relative) != digest:
            return False, f"backup checksum mismatch for {relative}"
    return True, None


def refused_same_run_divergences(
    repo: Path,
    owner: AgentOwnerIdentity,
    hoods: tuple[str, ...],
    owner_content: tuple[str, ...],
    merge_base: str | None,
    git_bytes_runner: GitBytesRunner,
) -> tuple[str, ...]:
    del owner_content
    refused: list[str] = []
    for hood in hoods:
        base_runs = read_merge_base_runs(
            repo, owner, (hood,), merge_base, git_bytes_runner
        )
        relative = snapshot_path(owner, hood)
        local = repo / relative
        if not local.is_file():
            continue
        upstream_bytes = git_optional_bytes(
            repo,
            git_bytes_runner,
            ["show", f"@{{upstream}}:{relative}"],
            "replay_upstream_snap",
        )
        if upstream_bytes is None:
            continue
        try:
            upstream_snapshot = decode_hood_snapshot(loads(upstream_bytes.decode()))
        except (OSError, UnicodeDecodeError, AgentsSyncFormatError, ValueError):
            continue
        merge: ReplayHoodMergeDecision = decide_replay_hood_merge(
            local_owner_username=owner.username,
            local_owner_machine=owner.machine_name,
            local_hood=hood,
            upstream_owner_username=upstream_snapshot.owner.username,
            upstream_owner_machine=upstream_snapshot.owner.machine_name,
            upstream_hood=upstream_snapshot.local_hood,
        )
        if merge.action != REPLAY_HOOD_ACTION_MERGE:
            refused.append(f"{hood}: {merge.reason}")
            continue
        local_snapshot = read_hood_snapshot(local)
        local_runs = {run.global_name: run for run in local_snapshot.runs}
        for run in upstream_snapshot.runs:
            local_run = local_runs.get(run.global_name)
            if local_run is None:
                continue
            base_run = base_runs.get(run.global_name)
            if base_run is not None:
                for field in (
                    "state",
                    "started_at",
                    "finished_at",
                    "dismissed_at",
                    "metadata",
                    "commits",
                ):
                    current_value = replay_run_field(local_run, field)
                    previous_value = replay_run_field(run, field)
                    base_value = replay_run_field(base_run.record, field)
                    field_decision = decide_replay_byte_divergence(
                        replay_value_bytes(current_value),
                        replay_value_bytes(previous_value),
                        base=replay_value_bytes(base_value),
                    )
                    if field_decision.action == REPLAY_BYTES_REFUSE:
                        refused.append(
                            f"{run.global_name}:{field}: {field_decision.reason}"
                        )
            current_files = dict(local_run.files)
            previous_files = dict(run.files)
            for kind in current_files.keys() | previous_files.keys():
                current_ref = current_files.get(kind)
                previous_ref = previous_files.get(kind)
                current_bytes = (
                    file_bytes(repo / current_ref.path)
                    if current_ref is not None
                    else None
                )
                previous_bytes = (
                    git_optional_bytes(
                        repo,
                        git_bytes_runner,
                        ["show", f"@{{upstream}}:{previous_ref.path}"],
                        "replay_upstream_run",
                    )
                    if previous_ref is not None
                    else None
                )
                if current_bytes is None and previous_bytes is None:
                    continue
                run_decision: ReplayByteDivergenceDecision = (
                    decide_replay_byte_divergence(
                        current_bytes or b"",
                        previous_bytes or b"",
                        base=base_run.payloads.get(kind) if base_run else None,
                    )
                )
                if run_decision.action == REPLAY_BYTES_REFUSE:
                    refused.append(f"{run.global_name}:{kind}: {run_decision.reason}")
    return tuple(refused)


def _copy_repo_file(repo: Path, destination_root: Path, relative: str) -> None:
    source = repo / relative
    if not source.is_file():
        return
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _checksum_tree(root: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {PROGRESS_NAME, CHECKSUMS_NAME}:
            continue
        checksums[relative] = sha256(path.read_bytes()).hexdigest()
    return checksums


def _git_lines(
    repo: Path, git_runner: GitRunner, args: list[str], op: str
) -> tuple[str, ...]:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line)
