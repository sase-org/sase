"""Producer path for building and publishing Rust prebuild cache sets."""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase.dev_update.models import DevCommandRunner
from sase.dev_update.prebuild_cache import (
    COMPLETED_SET_RETENTION,
    DEFAULT_PROFILE,
    EXTENSION_FILENAME,
    LSP_BINARY_NAME,
    MISS_COMMIT_MISMATCH,
    MISS_STAMP_MISSING,
    PROFILE_ENV,
    SCHEMA_VERSION,
    RustPrebuildConsumeOutcome,
    RustPrebuildProvenance,
    atomic_write_json,
    completed_stamps,
    current_provenance,
    prebuild_miss,
    prebuild_set_key,
    resolve_commit,
    sha256_file,
    write_last_result,
)

log = logging.getLogger(__name__)


def produce_prebuild(
    *,
    source_root: Path,
    upstream_ref: str,
    target_python: str,
    profile: str | None,
    root: Path | None,
    run: DevCommandRunner,
    which: Callable[[str], str | None],
    now: Callable[[], float],
    cache_root: Callable[[], Path],
    code_swap_writer_active: Callable[[], bool],
    classify_upstream: Callable[[Path], Any],
) -> RustPrebuildConsumeOutcome:
    """Build and stamp a cache set for the observed upstream commit."""
    cache = root or cache_root()
    active_profile = profile or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    cache.mkdir(parents=True, exist_ok=True)

    lock_path = cache / "prebuild.lock"
    with _nonblocking_file_lock(lock_path) as acquired:
        if not acquired:
            outcome = prebuild_miss(MISS_STAMP_MISSING)
            write_last_result(cache, outcome, now=now)
            return outcome
        try:
            if code_swap_writer_active():
                outcome = prebuild_miss(MISS_STAMP_MISSING)
                write_last_result(cache, outcome, now=now)
                return outcome
            commit = resolve_commit(source_root, upstream_ref, run)
            if commit is None:
                outcome = prebuild_miss(MISS_COMMIT_MISMATCH)
                write_last_result(cache, outcome, now=now)
                return outcome
            if not _live_checkout_still_behind(
                source_root,
                upstream_ref,
                commit,
                run,
                classify_upstream=classify_upstream,
            ):
                outcome = prebuild_miss(MISS_COMMIT_MISMATCH)
                write_last_result(cache, outcome, now=now)
                return outcome

            mirror = cache / "sase-core"
            if not ensure_mirror(source_root, mirror, commit, run):
                outcome = prebuild_miss(MISS_COMMIT_MISMATCH)
                write_last_result(cache, outcome, now=now)
                return outcome
            provenance = current_provenance(
                mirror,
                core_commit=commit,
                target_python=target_python,
                profile=active_profile,
                run=run,
            )
            if provenance is None:
                outcome = prebuild_miss(MISS_STAMP_MISSING)
                write_last_result(cache, outcome, now=now)
                return outcome

            set_key = prebuild_set_key(provenance)
            set_dir = cache / "sets" / set_key
            if (set_dir / "stamp.json").is_file():
                _prune_completed_sets(cache)
                outcome = RustPrebuildConsumeOutcome(True, "hit", set_key=set_key)
                write_last_result(cache, outcome, now=now)
                return outcome
            tmp_dir = set_dir.with_name(f".{set_key}.{os.getpid()}.tmp")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                _build_set(
                    mirror,
                    tmp_dir,
                    provenance,
                    target_python=target_python,
                    run=run,
                    which=which,
                )
                os.replace(tmp_dir, set_dir)
            except Exception:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                outcome = prebuild_miss(MISS_STAMP_MISSING)
                write_last_result(cache, outcome, now=now)
                return outcome
            _prune_completed_sets(cache)
            outcome = RustPrebuildConsumeOutcome(True, "hit", set_key=set_key)
            write_last_result(cache, outcome, now=now)
            return outcome
        except Exception:
            log.debug("Rust prebuild producer failed", exc_info=True)
            outcome = prebuild_miss(MISS_STAMP_MISSING)
            write_last_result(cache, outcome, now=now)
            return outcome


class _nonblocking_file_lock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def __exit__(self, *_exc: object) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _live_checkout_still_behind(
    source_root: Path,
    upstream_ref: str,
    requested_commit: str,
    run: DevCommandRunner,
    *,
    classify_upstream: Callable[[Path], Any],
) -> bool:
    try:
        status = classify_upstream(source_root)
    except Exception:
        return False
    if not status.strictly_behind or status.upstream != upstream_ref:
        return False
    observed = resolve_commit(
        Path(status.root),
        status.upstream or upstream_ref,
        run,
    )
    return observed == requested_commit


def ensure_mirror(
    live_root: Path,
    mirror: Path,
    commit: str,
    run: DevCommandRunner,
) -> bool:
    if not (mirror / ".git").exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        clone = run(
            (
                "git",
                "clone",
                "--shared",
                "--no-checkout",
                str(live_root),
                str(mirror),
            )
        )
        if clone.returncode != 0:
            return False
    fetch = run(
        (
            "git",
            "-C",
            str(mirror),
            "fetch",
            "--quiet",
            "--no-tags",
            str(live_root),
            commit,
        )
    )
    if fetch.returncode != 0:
        return False
    checkout = run(
        ("git", "-C", str(mirror), "checkout", "--force", "--detach", commit)
    )
    return checkout.returncode == 0


def _build_set(
    mirror: Path,
    set_dir: Path,
    provenance: RustPrebuildProvenance,
    *,
    target_python: str,
    run: DevCommandRunner,
    which: Callable[[str], str | None],
) -> None:
    artifacts_dir = set_dir / "artifacts"
    dist_dir = set_dir / "dist"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)
    py_target = set_dir / "target" / "py"
    lsp_target = set_dir / "target" / "lsp"
    maturin = _maturin_executable(target_python)
    py_env = _build_env(
        {
            "VIRTUAL_ENV": str(Path(target_python).parent.parent),
            "PYO3_USE_ABI3_FORWARD_COMPATIBILITY": "1",
            "CARGO_TARGET_DIR": str(py_target),
        }
    )
    maturin_result = run(
        _low_priority_argv(
            (
                maturin,
                "build",
                "--profile",
                provenance.profile,
                "--out",
                str(dist_dir),
            ),
            which=which,
        ),
        cwd=mirror / "crates" / "sase_core_py",
        env=py_env,
    )
    if maturin_result.returncode != 0:
        raise RuntimeError(maturin_result.stderr or "maturin build failed")
    wheel = _newest_wheel(dist_dir)
    if wheel is None:
        raise RuntimeError("maturin did not produce a wheel")
    extension_path = artifacts_dir / EXTENSION_FILENAME
    _extract_extension(wheel, extension_path)

    lsp_env = _build_env({"CARGO_TARGET_DIR": str(lsp_target)})
    cargo = run(
        _low_priority_argv(
            (
                "cargo",
                "build",
                "--profile",
                provenance.profile,
                "-p",
                "sase_xprompt_lsp",
            ),
            which=which,
        ),
        cwd=mirror,
        env=lsp_env,
    )
    if cargo.returncode != 0:
        raise RuntimeError(cargo.stderr or "cargo build failed")
    lsp_src = lsp_target / provenance.profile / LSP_BINARY_NAME
    lsp_path = artifacts_dir / LSP_BINARY_NAME
    shutil.copy2(lsp_src, lsp_path)
    lsp_path.chmod(lsp_path.stat().st_mode | 0o111)

    stamp = {
        "schema_version": SCHEMA_VERSION,
        **asdict(provenance),
        "artifacts": {
            "extension": {
                "path": str(extension_path.relative_to(set_dir)),
                "sha256": sha256_file(extension_path),
            },
            "lsp": {
                "path": str(lsp_path.relative_to(set_dir)),
                "sha256": sha256_file(lsp_path),
            },
        },
    }
    atomic_write_json(set_dir / "stamp.json", stamp)


def _maturin_executable(target_python: str) -> str:
    scripts_dir = Path(target_python).parent
    name = "maturin.exe" if os.name == "nt" else "maturin"
    candidate = scripts_dir / name
    return str(candidate) if candidate.exists() else name


def _build_env(extra: Mapping[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("CARGO_NET_RETRY", "10")
    env.setdefault("CARGO_HTTP_MULTIPLEXING", "false")
    env.update(extra)
    return env


def _low_priority_argv(
    argv: Sequence[str],
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    wrapped = tuple(argv)
    if which("nice"):
        wrapped = ("nice", "-n", "10", *wrapped)
    if which("ionice"):
        wrapped = ("ionice", "-c", "3", *wrapped)
    return wrapped


def _newest_wheel(dist_dir: Path) -> Path | None:
    wheels = sorted(
        (path for path in dist_dir.glob("*.whl") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return wheels[0] if wheels else None


def _extract_extension(wheel: Path, destination: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(f"/{EXTENSION_FILENAME}") or name == EXTENSION_FILENAME
            ),
            None,
        )
        if member is None:
            raise RuntimeError(f"{EXTENSION_FILENAME} missing from wheel")
        destination.write_bytes(archive.read(member))


def _prune_completed_sets(root: Path) -> None:
    for set_dir, _stamp in completed_stamps(root)[COMPLETED_SET_RETENTION:]:
        shutil.rmtree(set_dir, ignore_errors=True)
    sets_dir = root / "sets"
    try:
        tmp_dirs = [
            path
            for path in sets_dir.iterdir()
            if path.is_dir() and path.name.startswith(".")
        ]
    except OSError:
        return
    for path in tmp_dirs:
        shutil.rmtree(path, ignore_errors=True)
