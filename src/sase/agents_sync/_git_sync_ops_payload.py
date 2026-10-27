"""Agents payload staging, protection, commit, and worktree cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.agents_sync._git_sync_ops_git import agents_git_error
from sase.agents_sync.git import GitRunner
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.git_lock_retry import try_remove_stale_index_lock

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

AGENTS_SYNC_AUTO_COMMIT_TYPE = "agents_sync"
_AGENTS_PAYLOAD_PATHS = (
    "README.md",
    "schema.json",
    "users",
    "agents",
    "families",
    "sessions",
)
_LEGACY_MANIFEST_PATH = "manifest.json"


def commit_agents_payload_if_dirty(
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    *,
    extra_paths: tuple[str, ...] = (),
    protection_scope: PublicationProtectionScope | None = None,
) -> bool | str:
    protection_error = _verify_agents_payload_protection(
        repo,
        git_runner,
        scope=protection_scope,
    )
    if protection_error is not None:
        return protection_error
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    staged_paths = (
        *payload_paths,
        *(
            path
            for path in extra_paths
            if (repo / path).exists() or _tracked_path(repo, path, git_runner)
        ),
    )
    if not staged_paths:
        return False
    staged = git_runner(
        repo,
        ["add", "--force", "--", *staged_paths],
        op="agents_sync.stage",
    )
    if staged.returncode != 0:
        return agents_git_error("could not stage agents sidecar payload", staged)
    if extra_paths and protection_scope is not None:
        from sase.agents_sync.prompt_archive.protection import (
            unstage_unpublishable_archive_paths,
        )

        withheld = unstage_unpublishable_archive_paths(
            repo,
            git_runner,
            scope=protection_scope,
            archive_paths=extra_paths,
        )
        if withheld is not None:
            return withheld
    dirty = git_runner(
        repo,
        ["diff", "--cached", "--quiet", "--", *staged_paths],
        op="agents_sync.diff_staged",
    )
    if dirty.returncode == 0:
        return False
    if dirty.returncode != 1:
        return agents_git_error(
            "could not inspect staged agents sidecar changes",
            dirty,
        )
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            apply_auto_commit_type_tag(
                f"chore(agents): sync from {owner.username}.{owner.machine_name}",
                AGENTS_SYNC_AUTO_COMMIT_TYPE,
            ),
        ],
        op="agents_sync.commit",
    )
    if committed.returncode != 0:
        return agents_git_error("could not commit agents sidecar payload", committed)
    return True


def _candidate_rejection_blocked(
    lookup: object,
    scope: PublicationProtectionScope | None,
    relative: str,
    data: bytes,
) -> bool:
    """Return whether a GH013 rejection already blocked these exact bytes.

    A failed lookup never withholds on its own; the fresh scan below still
    decides. Only a durable ``blocked`` record for this exact digest keeps a
    rebuilt candidate out of staging, so recovery cannot replay rejected
    bytes through a path that bypasses snapshot gating.
    """

    if scope is None:
        return False
    import hashlib

    try:
        record = lookup(  # type: ignore[operator]
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative,
            sha256=hashlib.sha256(data).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        return False
    return isinstance(record, dict) and record.get("status") == "blocked"


def _verify_agents_payload_protection(
    repo: Path,
    git_runner: GitRunner,
    *,
    scope: PublicationProtectionScope | None = None,
) -> str | None:
    """Fail-closed pre-stage verification for the agents payload worktree.

    Scans only blobs that differ from ``HEAD`` under the agents payload
    paths — the exact candidate bytes staging would commit — never the whole
    upstream history. Existing dirty or pending worktree content cannot evade
    the guard because any worktree blob that is not already committed is a
    candidate. Returns an error string when any candidate cannot pass a
    complete text scan, or when verification itself cannot run; ``None``
    means every candidate is clean. The reusable scope boundary stays
    available to the prompt-archive staging without imposing
    archive-specific behavior here, so only agents payload paths are
    covered. The protection modules stay out of the TUI startup closure,
    so they are imported here instead of at module top level.
    """

    from sase.agents_sync.publication_protection import (
        MAX_PUBLICATION_SCAN_BYTES,
        lookup_publication_content_record,
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    max_bytes = scope.max_bytes if scope is not None else MAX_PUBLICATION_SCAN_BYTES
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    if not payload_paths:
        return None
    candidates = _changed_payload_files(repo, git_runner, payload_paths)
    if isinstance(candidates, str):
        return candidates
    blocked = 0
    for relative in candidates:
        candidate_path = repo / relative
        if candidate_path.is_symlink():
            return (
                "agents payload failed protection verification: "
                f"unsupported symlink at {relative!r}"
            )
        if not candidate_path.is_file():
            # Staging a deletion removes bytes; nothing to scan.
            continue
        try:
            data = candidate_path.read_bytes()
        except OSError:
            return (
                "agents payload failed protection verification: "
                f"could not read {relative!r}"
            )
        if not data:
            continue
        if scope is not None and _candidate_rejection_blocked(
            lookup_publication_content_record, scope, relative, data
        ):
            blocked += 1
            continue
        verdict = scan_publication_bytes(data, max_bytes=max_bytes)
        if scope is not None:
            try:
                record_publication_bytes_scan(
                    scope.project_key,
                    repository_identity=scope.repository_identity,
                    relative_destination=relative,
                    verdict=verdict,
                )
            except Exception:  # noqa: BLE001 - the scan verdict still holds.
                pass
        if not verdict.is_publishable:
            blocked += 1
            continue
        if verdict.sha256 is None:
            blocked += 1
            continue
        try:
            if _sha256_file(candidate_path) != verdict.sha256:
                return (
                    "agents payload failed protection verification: "
                    f"{relative!r} changed between scanning and writing"
                )
        except OSError:
            return (
                "agents payload failed protection verification: "
                f"could not re-read {relative!r}"
            )
    if blocked:
        return (
            "agents payload failed protection verification: "
            f"{blocked} file(s) withheld; see `sase doctor` for details"
        )
    return None


def _changed_payload_files(
    repo: Path,
    git_runner: GitRunner,
    payload_paths: tuple[str, ...],
) -> tuple[str, ...] | str:
    """List worktree blobs under payload paths that differ from ``HEAD``."""

    status = git_runner(
        repo,
        ["status", "--porcelain=v1", "-z", "--", *payload_paths],
        op="agents_sync.protection_status",
    )
    if status.returncode != 0:
        return agents_git_error(
            "could not inspect agents sidecar worktree for protection",
            status,
        )
    changed: list[str] = []
    tokens = status.stdout.split("\0") if status.stdout else []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            return (
                "agents payload failed protection verification: "
                "could not parse worktree status"
            )
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC" or y in "RC":
            # Rename/copy entries carry the other side as the next token;
            # both sides are candidates because staging touches them.
            if index < len(tokens) and tokens[index]:
                changed.append(tokens[index])
                index += 1
        if x == "U" or y == "U" or x == "A" and y == "A":
            return (
                "agents payload failed protection verification: "
                f"could not verify conflicted file at {path!r}"
            )
        if y == "D":
            # Staging a deletion removes bytes; nothing to scan.
            continue
        if path:
            changed.append(path)
    ignored = git_runner(
        repo,
        [
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *payload_paths,
        ],
        op="agents_sync.protection_ignored",
    )
    if ignored.returncode != 0:
        return agents_git_error(
            "could not inspect ignored agents sidecar files for protection",
            ignored,
        )
    changed.extend(token for token in ignored.stdout.split("\0") if token)
    return tuple(dict.fromkeys(changed))


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_payload_paths(repo: Path, git_runner: GitRunner) -> tuple[str, ...]:
    if (repo / _LEGACY_MANIFEST_PATH).exists() or _tracked_legacy_manifest(
        repo, git_runner
    ):
        return (_LEGACY_MANIFEST_PATH, *_AGENTS_PAYLOAD_PATHS)
    return _AGENTS_PAYLOAD_PATHS


def _existing_or_tracked_payload_paths(
    repo: Path, git_runner: GitRunner
) -> tuple[str, ...]:
    return tuple(
        path
        for path in _candidate_payload_paths(repo, git_runner)
        if (repo / path).exists() or _tracked_path(repo, path, git_runner)
    )


def _tracked_path(repo: Path, path: str, git_runner: GitRunner) -> bool:
    tracked = git_runner(
        repo,
        ["ls-files", "--", path],
        op="agents_sync.extra_path_tracked",
    )
    return tracked.returncode == 0 and bool(tracked.stdout.strip())


def _tracked_legacy_manifest(repo: Path, git_runner: GitRunner) -> bool:
    tracked = git_runner(
        repo,
        ["ls-files", "--error-unmatch", "--", _LEGACY_MANIFEST_PATH],
        op="agents_sync.legacy_manifest_tracked",
    )
    return tracked.returncode == 0


def clean_agents_payload_worktree(
    repo: Path,
    git_runner: GitRunner,
) -> str | None:
    """Restore the regenerable sidecar payload to ``HEAD``.

    Agents sync shares this clone with ``sase repo open``, so either actor may
    have reset the checkout since the previous operation. Keep recovery
    idempotent and never stash payload writes: every payload path is rebuilt
    from local agent artifacts on each pass, making discarded writes safe to
    regenerate.
    """

    _clear_stale_agents_index_lock(repo, git_runner)
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *payload_paths],
        op="agents_sync.payload_reset_index",
    )
    if reset.returncode != 0:
        return agents_git_error("could not reset agents sidecar payload index", reset)

    tracked = git_runner(
        repo,
        ["ls-files", "--", *payload_paths],
        op="agents_sync.payload_tracked",
    )
    if tracked.returncode != 0:
        return agents_git_error("could not inspect tracked agents payload", tracked)
    tracked_paths = tuple(tracked.stdout.splitlines())
    restore_roots = tuple(
        root
        for root in payload_paths
        if any(path == root or path.startswith(f"{root}/") for path in tracked_paths)
    )
    if restore_roots:
        restored = git_runner(
            repo,
            ["checkout", "--", *restore_roots],
            op="agents_sync.payload_restore",
        )
        if restored.returncode != 0:
            return agents_git_error(
                "could not restore tracked agents sidecar payload", restored
            )

    cleaned = git_runner(
        repo,
        ["clean", "-fdx", "--", *payload_paths],
        op="agents_sync.payload_clean",
    )
    if cleaned.returncode != 0:
        return agents_git_error(
            "could not remove untracked agents sidecar payload", cleaned
        )
    return None


def _clear_stale_agents_index_lock(repo: Path, git_runner: GitRunner) -> None:
    del git_runner
    try_remove_stale_index_lock(repo)
