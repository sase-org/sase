"""Object, pack, and base-commit capture for verified snapshots."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sase.workspace_provider._snapshot_git import require_git, run_git_bytes
from sase.workspace_provider._snapshot_model import (
    SNAPSHOT_PACK_NAME,
    PreservationError,
    SNAPSHOT_MAX_BYTES,
    SourceState,
)


def validate_index_objects(
    repo_root: Path,
    state: SourceState,
    *,
    env: dict[str, str],
) -> None:
    shas = {entry.sha for entry in state.entries if entry.mode != "160000"}
    details = _batch_check_objects(repo_root, shas, env=env, label="index object")
    for sha, (kind, _size) in details.items():
        if kind != "blob":
            raise PreservationError(
                f"index object {sha} has unexpected type {kind}, expected blob"
            )


def base_commit_objects(
    repo_root: Path, *, state: SourceState, env: dict[str, str]
) -> tuple[dict[str, object], set[str]]:
    refs = _remote_tracking_refs(repo_root, env=env)
    if not refs:
        commits = _rev_list_objects(repo_root, state.head, env=env)
        return (
            {
                "mode": "self-contained",
                "boundary_commits": [],
                "remotes": [],
                "remote_tracking_refs": [],
            },
            commits,
        )

    commits_output = require_git(
        run_git_bytes(
            repo_root,
            "rev-list",
            "--objects",
            state.head,
            "--not",
            "--remotes",
            env=env,
        ),
        "git rev-list --objects HEAD --not --remotes",
    )
    commits = _shas_from_object_list(commits_output)
    boundary_output = require_git(
        run_git_bytes(
            repo_root,
            "rev-list",
            "--boundary",
            state.head,
            "--not",
            "--remotes",
            env=env,
        ),
        "git rev-list --boundary HEAD --not --remotes",
    )
    boundaries = sorted(
        {
            line[1:].decode("ascii").split(" ", 1)[0]
            for line in boundary_output.splitlines()
            if line.startswith(b"-")
        }
    )
    if not commits and not boundaries:
        boundaries = [state.head]

    configured_names = (
        require_git(run_git_bytes(repo_root, "remote", env=env), "git remote")
        .decode("utf-8", "surrogateescape")
        .splitlines()
    )
    remote_names = {
        name
        for ref in refs
        if (name := _remote_name_for_ref(ref["ref"], configured_names))
    }
    if any(_remote_name_for_ref(ref["ref"], configured_names) is None for ref in refs):
        invalid = sorted(
            ref["ref"]
            for ref in refs
            if _remote_name_for_ref(ref["ref"], configured_names) is None
        )
        raise PreservationError(
            "remote-tracking refs have no matching configured remote: "
            + ", ".join(invalid)
        )
    remotes = _remote_fetch_urls(repo_root, remote_names, env=env)
    return (
        {
            "mode": "published",
            "boundary_commits": boundaries,
            "remotes": remotes,
            "remote_tracking_refs": refs,
        },
        commits,
    )


def _remote_tracking_refs(
    repo_root: Path, *, env: dict[str, str]
) -> list[dict[str, str]]:
    output = require_git(
        run_git_bytes(
            repo_root,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            "refs/remotes/",
            env=env,
        ),
        "git for-each-ref refs/remotes",
    )
    refs: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split(b"\0", 1)
        if len(fields) != 2:
            continue
        ref, sha = fields
        refs.append(
            {
                "ref": ref.decode("utf-8", "surrogateescape"),
                "sha": sha.decode("ascii"),
            }
        )
    return sorted(refs, key=lambda item: item["ref"])


def _remote_name_for_ref(ref: str, names: list[str]) -> str | None:
    matches = [name for name in names if ref.startswith(f"refs/remotes/{name}/")]
    return max(matches, key=len) if matches else None


def _remote_fetch_urls(
    repo_root: Path, names: set[str], *, env: dict[str, str]
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name in sorted(names):
        result = run_git_bytes(repo_root, "remote", "get-url", "--all", name, env=env)
        urls = require_git(result, f"git remote get-url {name}")
        values = [line.decode("utf-8", "surrogateescape") for line in urls.splitlines()]
        if not values:
            raise PreservationError(f"remote {name} has no fetch URL")
        records.extend(
            {"name": name, "fetch_url": _absolute_fetch_url(repo_root, url)}
            for url in values
        )
    return records


def _absolute_fetch_url(repo_root: Path, url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme == "file" and parsed.netloc in {"", "localhost"}:
        path = Path(unquote(parsed.path))
        if not path.is_absolute():
            path = repo_root / path
        return path.resolve(strict=False).as_uri()
    if parsed.scheme:
        return url
    if re.match(r"^[^/]+@[^/:]+:", url) or re.match(r"^[^/:]+:", url):
        return url
    path = Path(url)
    if not path.is_absolute():
        path = repo_root / path
    return str(path.resolve(strict=False))


def object_shas(
    repo_root: Path,
    *,
    state: SourceState,
    index_tree: str | None,
    worktree_tree: str,
    committed_shas: set[str],
    env: dict[str, str],
) -> set[str]:
    head_objects = _tree_objects(repo_root, state.base_tree, env=env)
    worktree_objects = _tree_objects(repo_root, worktree_tree, env=env)
    index_objects: set[str] = set()
    if index_tree is not None:
        index_objects = _tree_objects(repo_root, index_tree, env=env)
    work_index_objects = worktree_objects | index_objects
    unmerged_blobs = {
        entry.sha
        for entry in state.entries
        if entry.stage != 0 and entry.mode != "160000"
    }
    tree_gitlinks = _gitlink_shas(
        repo_root,
        (state.base_tree, worktree_tree, *((index_tree,) if index_tree else ())),
        env=env,
    )
    all_gitlinks = tree_gitlinks | {
        entry.sha for entry in state.entries if entry.mode == "160000"
    }
    changed_objects = work_index_objects | unmerged_blobs
    pack_shas = set(committed_shas) | (changed_objects - head_objects)
    pack_shas.add(worktree_tree)
    if index_tree is not None:
        pack_shas.add(index_tree)
    pack_shas.difference_update(all_gitlinks)
    return {sha for sha in pack_shas if sha}


def _rev_list_objects(repo_root: Path, rev: str, *, env: dict[str, str]) -> set[str]:
    output = require_git(
        run_git_bytes(repo_root, "rev-list", "--objects", "--no-walk", rev, env=env),
        f"git rev-list --objects {rev}",
    )
    return _shas_from_object_list(output)


def _tree_objects(repo_root: Path, tree: str, *, env: dict[str, str]) -> set[str]:
    shas = {tree}
    output = require_git(
        run_git_bytes(
            repo_root, "ls-tree", "-r", "-t", "-z", "--full-tree", tree, env=env
        ),
        f"git ls-tree {tree}",
    )
    for item in output.split(b"\0"):
        if not item:
            continue
        meta = item.split(b"\t", 1)[0]
        parts = meta.split(b" ")
        if len(parts) >= 3 and parts[0] != b"160000":
            shas.add(parts[2].decode("ascii"))
    return shas


def _gitlink_shas(
    repo_root: Path, trees: tuple[str, ...], *, env: dict[str, str]
) -> set[str]:
    shas: set[str] = set()
    for tree in set(trees):
        output = require_git(
            run_git_bytes(
                repo_root, "ls-tree", "-r", "-t", "-z", "--full-tree", tree, env=env
            ),
            f"git ls-tree {tree}",
        )
        for item in output.split(b"\0"):
            if not item:
                continue
            fields = item.split(b"\t", 1)[0].split(b" ")
            if len(fields) >= 3 and fields[0] == b"160000":
                shas.add(fields[2].decode("ascii"))
    return shas


def _batch_check_objects(
    repo_root: Path,
    shas: set[str],
    *,
    env: dict[str, str] | None,
    label: str,
) -> dict[str, tuple[str, int]]:
    if not shas:
        return {}
    ordered = sorted(shas)
    output = require_git(
        run_git_bytes(
            repo_root,
            "cat-file",
            "--batch-check",
            env=env,
            input_bytes=("\n".join(ordered) + "\n").encode("ascii"),
        ),
        f"git cat-file --batch-check ({label})",
    )
    lines = output.splitlines()
    if len(lines) != len(ordered):
        raise PreservationError(
            f"git cat-file --batch-check returned {len(lines)} rows for "
            f"{len(ordered)} {label}s"
        )
    details: dict[str, tuple[str, int]] = {}
    for expected, line in zip(ordered, lines, strict=True):
        fields = line.split()
        if len(fields) == 2 and fields[1] == b"missing":
            raise PreservationError(f"{label} {expected} is missing")
        if len(fields) != 3 or fields[0].decode("ascii") != expected:
            raise PreservationError(
                f"could not parse git cat-file --batch-check row for {label} "
                f"{expected}: {line!r}"
            )
        try:
            details[expected] = (fields[1].decode("ascii"), int(fields[2]))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PreservationError(
                f"could not parse git cat-file --batch-check size for {label} "
                f"{expected}: {line!r}"
            ) from exc
    return details


def account_pack_objects(
    repo_root: Path, shas: set[str], *, env: dict[str, str]
) -> None:
    details = _batch_check_objects(
        repo_root, shas, env=env, label="snapshot pack object"
    )
    total = 0
    for sha in sorted(details):
        total = _account_bytes(total, details[sha][1], f"object {sha}")


def _shas_from_object_list(output: bytes) -> set[str]:
    shas: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        sha = line.split(b" ", 1)[0].decode("ascii")
        if sha:
            shas.add(sha)
    return shas


def write_pack(
    repo_root: Path,
    shas: set[str],
    pack_path: Path,
    *,
    env: dict[str, str],
) -> None:
    payload = ("\n".join(sorted(shas)) + "\n").encode("ascii")
    result = run_git_bytes(
        repo_root,
        "pack-objects",
        "--stdout",
        "--delta-base-offset",
        env=env,
        input_bytes=payload,
    )
    packed = require_git(result, "git pack-objects")
    if not packed:
        raise PreservationError("git pack-objects wrote an empty pack")
    _account_bytes(0, len(packed), SNAPSHOT_PACK_NAME)
    pack_path.write_bytes(packed)


def verify_pack(pack_path: Path, *, required_shas: set[str]) -> None:
    """Prove the pack is self-contained without touching the source checkout.

    ``git index-pack`` outside a repository aborts (SIGSEGV on this host), so
    verification unpacks into a throwaway git dir and checks required objects.
    """
    verify_dir = pack_path.parent / ".verify-git"
    try:
        verify_dir.mkdir()
        require_git(
            run_git_bytes(verify_dir, "init", "--bare"),
            "git init --bare",
        )
        require_git(
            run_git_bytes(
                verify_dir,
                "unpack-objects",
                "-q",
                input_bytes=pack_path.read_bytes(),
            ),
            "git unpack-objects",
        )
        details = _batch_check_objects(
            verify_dir, required_shas, env=None, label="packed snapshot object"
        )
        for sha, (kind, _size) in details.items():
            if kind not in {"commit", "tree", "blob"}:
                raise PreservationError(
                    f"snapshot pack object {sha} has unexpected type {kind}"
                )
    finally:
        shutil.rmtree(verify_dir, ignore_errors=True)


def _account_bytes(total: int, added: int, label: str) -> int:
    new_total = total + added
    if added > SNAPSHOT_MAX_BYTES or new_total > SNAPSHOT_MAX_BYTES:
        raise PreservationError(
            f"snapshot payload {label} is {added} bytes; "
            f"total {new_total} exceeds the {SNAPSHOT_MAX_BYTES}-byte cap"
        )
    return new_total


__all__ = [
    "account_pack_objects",
    "base_commit_objects",
    "object_shas",
    "validate_index_objects",
    "verify_pack",
    "write_pack",
]
