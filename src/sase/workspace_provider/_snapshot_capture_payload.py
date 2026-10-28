"""Capture trees, packs, and manifests into a rescue directory."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sase.workspace_provider._rescue_store import (
    RESCUE_MANIFEST_NAME,
    RESCUE_SCHEMA_VERSION,
)
from sase.workspace_provider._snapshot_capture_common import is_managed_sidecar_rel
from sase.workspace_provider._snapshot_git import (
    file_mode_for_path,
    nested_git_root,
    read_worktree_bytes,
    require_git,
    run_git_bytes,
    safe_repo_path,
    special_index_paths,
    snapshot_env,
    status_paths,
)
from sase.workspace_provider._snapshot_model import (
    DIR_OPERATION_MARKERS,
    FILE_OPERATION_MARKERS,
    SNAPSHOT_INDEX_STAGE_NAME,
    SNAPSHOT_KIND,
    SNAPSHOT_MAX_BYTES,
    SNAPSHOT_PACK_NAME,
    IndexEntry,
    PreservationError,
    SnapshotRecord,
    SourceState,
)


def capture_into(
    repo_root: Path,
    *,
    state: SourceState,
    rescue_dir: Path,
    snapshot_id: str,
    stamp: str,
    workspace_dir: Path,
    workspace_num: int,
    safe_label: str,
    reason: str,
) -> SnapshotRecord:
    object_dir = rescue_dir / "objects"
    object_dir.mkdir(parents=True, exist_ok=True)
    (object_dir / "info").mkdir(exist_ok=True)
    (object_dir / "pack").mkdir(exist_ok=True)
    env = snapshot_env(object_dir=object_dir, alternate_dirs=(state.object_dir,))
    worktree_entries = _worktree_entries(repo_root, state, env=env)
    worktree_tree = _write_tree(
        repo_root,
        worktree_entries,
        object_dir=object_dir,
        alternate_dirs=(state.object_dir,),
        tmp_index=rescue_dir / ".tmp-worktree-index",
    )
    index_tree = _index_tree(
        repo_root,
        state,
        object_dir=object_dir,
        tmp_index=rescue_dir / ".tmp-index",
    )
    unmerged = any(entry.stage != 0 for entry in state.entries)
    index_stage_path = rescue_dir / SNAPSHOT_INDEX_STAGE_NAME
    index_stage_path.write_bytes(state.ls_files_z)
    _validate_index_objects(repo_root, state, env=env)
    operation_markers = _copy_operation_markers(state, rescue_dir)
    base, committed_shas = _base_commit_objects(repo_root, state=state, env=env)
    shas = _object_shas(
        repo_root,
        state=state,
        index_tree=index_tree,
        worktree_tree=worktree_tree,
        committed_shas=committed_shas,
        env=env,
    )
    _account_pack_objects(repo_root, shas, env=env)
    pack_path = rescue_dir / SNAPSHOT_PACK_NAME
    _write_pack(repo_root, shas, pack_path, env=env)
    _verify_pack(pack_path, required_shas=shas)
    _cleanup_capture_temps(rescue_dir, object_dir)
    if not pack_path.is_file() or pack_path.stat().st_size == 0:
        raise PreservationError("snapshot pack is missing after capture")
    if not index_stage_path.is_file():
        raise PreservationError("index-stage payload is missing after capture")
    manifest = {
        "schema_version": RESCUE_SCHEMA_VERSION,
        "kind": SNAPSHOT_KIND,
        "snapshot_id": snapshot_id,
        "timestamp": stamp,
        "repo_root": str(repo_root),
        "workspace_dir": str(workspace_dir),
        "workspace_num": workspace_num,
        "label": safe_label,
        "reason": reason,
        "branch": state.branch,
        "head": state.head,
        "source_fingerprint": asdict(state.fingerprint),
        "base_tree": state.base_tree,
        "base": base,
        "index_tree": index_tree,
        "worktree_tree": worktree_tree,
        "unmerged": unmerged,
        "operation_markers": operation_markers,
        "status_porcelain": state.status_z.decode("utf-8", "surrogateescape").replace(
            "\0", "\n"
        ),
        "files": _payload_names(rescue_dir),
        "payloads": {
            "pack": SNAPSHOT_PACK_NAME,
            "index_stage": SNAPSHOT_INDEX_STAGE_NAME,
        },
        "restore": {
            "objects": (
                "fetch the base commits from the recorded remote when the base mode is "
                f"published; then git unpack-objects < <rescue-dir>/{SNAPSHOT_PACK_NAME}"
            ),
            "head": f"git update-ref HEAD {state.head}",
            "worktree": (
                f"materialize tree {worktree_tree} into the worktree, "
                "then load the captured index"
            ),
            "index": (
                f"git read-tree {index_tree}"
                if index_tree is not None
                else (
                    "git update-index -z --index-info < "
                    f"<rescue-dir>/{SNAPSHOT_INDEX_STAGE_NAME}"
                )
            ),
        },
    }
    manifest_path = publish_manifest(rescue_dir, manifest)
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        manifest_path=manifest_path.resolve(strict=False),
        rescue_dir=rescue_dir.resolve(strict=False),
        head=state.head,
        base_tree=state.base_tree,
        index_tree=index_tree,
        worktree_tree=worktree_tree,
        pack_path=pack_path.resolve(strict=False),
        unmerged=unmerged,
    )


def publish_manifest(rescue_dir: Path, manifest: dict[str, object]) -> Path:
    """Write ``manifest.json`` only after payloads exist. Last step of capture."""
    payload = json.dumps(manifest, indent=2) + "\n"
    target = rescue_dir / RESCUE_MANIFEST_NAME
    tmp = rescue_dir / f".{RESCUE_MANIFEST_NAME}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    for key in ("kind", "snapshot_id", "head", "worktree_tree", "payloads"):
        if key not in loaded:
            raise PreservationError(f"published manifest missing {key}")
    if loaded.get("kind") != SNAPSHOT_KIND:
        raise PreservationError("published manifest is not a verified snapshot")
    return target


def _worktree_entries(
    repo_root: Path,
    state: SourceState,
    *,
    env: dict[str, str],
) -> list[IndexEntry]:
    # Preserve index stage-0 content by default. Only read live files where Git's
    # status reports a change, where a conflict has non-zero stages, or where an
    # index flag makes status insufficient evidence.
    entries_by_path = {
        entry.path: IndexEntry(mode=entry.mode, sha=entry.sha, stage=0, path=entry.path)
        for entry in state.entries
        if entry.stage == 0 and not is_managed_sidecar_rel(entry.path)
    }
    candidate_paths = {
        rel for rel in status_paths(state.status_z) if not is_managed_sidecar_rel(rel)
    }
    candidate_paths.update(
        entry.path
        for entry in state.entries
        if entry.stage != 0 and not is_managed_sidecar_rel(entry.path)
    )
    candidate_paths.update(special_index_paths(repo_root, env=env))

    for rel in sorted(candidate_paths):
        entries_by_path.pop(rel, None)
        if is_managed_sidecar_rel(rel):
            continue
        path = safe_repo_path(repo_root, rel)
        if not path.exists() and not os.path.lexists(path):
            continue
        if path.is_dir() and not path.is_symlink():
            nested = nested_git_root(repo_root, rel)
            if nested is not None:
                if is_managed_sidecar_rel(nested.relative_to(repo_root).as_posix()):
                    continue
                raise PreservationError(
                    f"refusing to snapshot nested repository content: {nested}"
                )
            continue
        data = read_worktree_bytes(path)
        sha = _hash_blob(repo_root, data, env=env)
        entries_by_path[rel] = IndexEntry(
            mode=file_mode_for_path(path), sha=sha, stage=0, path=rel
        )
    return [entries_by_path[rel] for rel in sorted(entries_by_path)]


def _hash_blob(repo_root: Path, data: bytes, *, env: dict[str, str]) -> str:
    result = run_git_bytes(
        repo_root,
        "hash-object",
        "-w",
        "--stdin",
        "--no-filters",
        env=env,
        input_bytes=data,
    )
    sha = require_git(result, "git hash-object").strip().decode("ascii")
    if not sha:
        raise PreservationError("git hash-object returned an empty sha")
    return sha


def _write_tree(
    repo_root: Path,
    entries: list[IndexEntry],
    *,
    object_dir: Path,
    alternate_dirs: tuple[Path, ...],
    tmp_index: Path,
) -> str:
    tmp_index.unlink(missing_ok=True)
    env = snapshot_env(
        index_file=tmp_index,
        object_dir=object_dir,
        alternate_dirs=alternate_dirs,
    )
    payload = b"".join(
        f"{entry.mode} {entry.sha} {entry.stage}\t".encode("ascii")
        + os.fsencode(entry.path)
        + b"\0"
        for entry in entries
    )
    require_git(
        run_git_bytes(
            repo_root,
            "update-index",
            "-z",
            "--index-info",
            env=env,
            input_bytes=payload,
        ),
        "git update-index --index-info",
    )
    sha = (
        require_git(
            run_git_bytes(repo_root, "write-tree", env=env),
            "git write-tree",
        )
        .strip()
        .decode("ascii")
    )
    if not sha:
        raise PreservationError("git write-tree returned an empty sha")
    return sha


def _index_tree(
    repo_root: Path,
    state: SourceState,
    *,
    object_dir: Path,
    tmp_index: Path,
) -> str | None:
    if any(entry.stage != 0 for entry in state.entries):
        return None
    if not state.index_path.is_file():
        return None
    shutil.copyfile(state.index_path, tmp_index)
    env = snapshot_env(
        index_file=tmp_index,
        object_dir=object_dir,
        alternate_dirs=(state.object_dir,),
    )
    result = run_git_bytes(repo_root, "write-tree", env=env)
    if result.returncode != 0:
        raise PreservationError(
            f"git write-tree for the index failed: "
            f"{(result.stderr or result.stdout).decode('utf-8', 'replace').strip()}"
        )
    sha = result.stdout.strip().decode("ascii")
    return sha or None


def _validate_index_objects(
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


def _base_commit_objects(
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


def _object_shas(
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


def _account_pack_objects(
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


def _write_pack(
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


def _verify_pack(pack_path: Path, *, required_shas: set[str]) -> None:
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


def _copy_operation_markers(state: SourceState, rescue_dir: Path) -> list[str]:
    found: list[str] = []
    dest_root = rescue_dir / "operation"
    for name in DIR_OPERATION_MARKERS:
        source = state.git_dir / name
        if source.is_dir():
            shutil.copytree(source, dest_root / name, symlinks=True)
            found.append(name)
    for name in FILE_OPERATION_MARKERS:
        source = state.git_dir / name
        if source.is_file():
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest_root / name)
            found.append(name)
    return sorted(found)


def _cleanup_capture_temps(rescue_dir: Path, object_dir: Path) -> None:
    shutil.rmtree(object_dir, ignore_errors=True)
    for child in rescue_dir.glob(".tmp-*"):
        try:
            child.unlink()
        except OSError:
            pass


def _payload_names(rescue_dir: Path) -> list[str]:
    names: list[str] = []
    for path in sorted(rescue_dir.iterdir()):
        if path.name.startswith(".") or path.name == RESCUE_MANIFEST_NAME:
            continue
        names.append(path.name)
    return names


def _account_bytes(total: int, added: int, label: str) -> int:
    new_total = total + added
    if added > SNAPSHOT_MAX_BYTES or new_total > SNAPSHOT_MAX_BYTES:
        raise PreservationError(
            f"snapshot payload {label} is {added} bytes; "
            f"total {new_total} exceeds the {SNAPSHOT_MAX_BYTES}-byte cap"
        )
    return new_total
