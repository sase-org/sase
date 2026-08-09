"""Best-effort Rust artifact prebuild cache for editable dev updates."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.core.paths import sase_subdir
from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevRustPrebuildResult,
)
from sase.version._git import classify_git_upstream

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_PROFILE = "dev-update"
PROFILE_ENV = "SASE_RUST_DEV_PROFILE"
EXTENSION_FILENAME = "sase_core_rs.abi3.so"
LSP_BINARY_NAME = "sase-xprompt-lsp.exe" if os.name == "nt" else "sase-xprompt-lsp"
PREBUILD_MARKER_KEY = "rust_prebuild"
COMPLETED_SET_RETENTION = 2

MISS_STAMP_MISSING = "stamp-missing"
MISS_COMMIT_MISMATCH = "commit-mismatch"
MISS_LOCKFILE_MISMATCH = "lockfile-mismatch"
MISS_RUSTC_MISMATCH = "rustc-mismatch"
MISS_PROFILE_MISMATCH = "profile-mismatch"
MISS_ABI_MISMATCH = "abi-mismatch"
MISS_INTERPRETER_MISMATCH = "interpreter-mismatch"
MISS_DIGEST_MISMATCH = "digest-mismatch"
MISS_COPY_FAILURE = "copy-failure"
MISS_HEALTH_CHECK_FAILED = "health-check-failed"
MISS_DISABLED = "disabled"

_FIELD_MISMATCH_REASONS = (
    ("core_commit", MISS_COMMIT_MISMATCH),
    ("cargo_lock_sha256", MISS_LOCKFILE_MISMATCH),
    ("rustc_version", MISS_RUSTC_MISMATCH),
    ("profile", MISS_PROFILE_MISMATCH),
    ("target_interpreter", MISS_INTERPRETER_MISMATCH),
    ("python_abi", MISS_ABI_MISMATCH),
)

CommandRunner = DevCommandRunner
Launcher = Callable[..., object]


@dataclass(frozen=True)
class _PythonIdentity:
    """Resolved target interpreter details used in prebuild provenance."""

    executable: str
    abi: str


@dataclass(frozen=True)
class _RustPrebuildProvenance:
    """Exact inputs that must match before a cached set can be installed."""

    core_commit: str
    cargo_lock_sha256: str
    rustc_version: str
    profile: str
    target_interpreter: str
    python_abi: str


@dataclass(frozen=True)
class _RustPrebuildConsumeOutcome:
    """Structured result exchanged between the consume command and executor."""

    hit: bool
    reason: str
    set_key: str | None = None

    def to_dev_result(self) -> DevRustPrebuildResult:
        return DevRustPrebuildResult(
            attempted=True,
            hit=self.hit,
            reason="hit" if self.hit else self.reason,
        )


def _cache_root() -> Path:
    """Return the production Rust prebuild cache root."""
    return sase_subdir("cache") / "rust-prebuild"


def schedule_rust_prebuild(
    status: Any,
    config: Any,
    *,
    launcher: Launcher | None = None,
    python: str | None = None,
) -> bool:
    """Launch one detached producer for the editable core update, if eligible."""
    if not getattr(config, "prebuild_rust", True):
        return False
    component = _editable_core_component(status)
    if component is None:
        return False
    source_root = getattr(component, "source_root", None)
    upstream_ref = getattr(component, "upstream_ref", None)
    if not source_root or not upstream_ref:
        return False
    executable = python or sys.executable
    argv = [
        executable,
        "-m",
        "sase.dev_update.prebuild",
        "produce",
        "--source-root",
        source_root,
        "--upstream-ref",
        upstream_ref,
        "--python",
        executable,
    ]
    launch = launcher or subprocess.Popen
    try:
        launch(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        log.debug("Failed to launch Rust prebuild producer", exc_info=True)
        return False
    return True


def _editable_core_component(status: Any) -> Any | None:
    """Return the editable core component from an update snapshot, if present."""
    for component in getattr(status, "components", ()):
        if (
            getattr(component, "role", None) == "core"
            and getattr(component, "install_type", None) == "editable"
            and getattr(component, "source_root", None)
            and getattr(component, "upstream_ref", None)
        ):
            return component
    return None


def _produce_prebuild(
    *,
    source_root: Path,
    upstream_ref: str,
    target_python: str,
    profile: str | None = None,
    root: Path | None = None,
    run: CommandRunner | None = None,
    which: Callable[[str], str | None] = shutil.which,
    now: Callable[[], float] = time.time,
) -> _RustPrebuildConsumeOutcome:
    """Build and stamp a cache set for the observed upstream commit."""
    cache = root or _cache_root()
    runner = run or _run_command
    active_profile = profile or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    cache.mkdir(parents=True, exist_ok=True)

    lock_path = cache / "prebuild.lock"
    with _nonblocking_file_lock(lock_path) as acquired:
        if not acquired:
            outcome = _miss(MISS_STAMP_MISSING)
            _write_last_result(cache, outcome, now=now)
            return outcome
        try:
            if _code_swap_writer_active():
                outcome = _miss(MISS_STAMP_MISSING)
                _write_last_result(cache, outcome, now=now)
                return outcome
            commit = _resolve_commit(source_root, upstream_ref, runner)
            if commit is None:
                outcome = _miss(MISS_COMMIT_MISMATCH)
                _write_last_result(cache, outcome, now=now)
                return outcome
            if not _live_checkout_still_behind(
                source_root,
                upstream_ref,
                commit,
                runner,
            ):
                outcome = _miss(MISS_COMMIT_MISMATCH)
                _write_last_result(cache, outcome, now=now)
                return outcome

            mirror = cache / "sase-core"
            if not _ensure_mirror(source_root, mirror, commit, runner):
                outcome = _miss(MISS_COMMIT_MISMATCH)
                _write_last_result(cache, outcome, now=now)
                return outcome
            provenance = _current_provenance(
                mirror,
                core_commit=commit,
                target_python=target_python,
                profile=active_profile,
                run=runner,
            )
            if provenance is None:
                outcome = _miss(MISS_STAMP_MISSING)
                _write_last_result(cache, outcome, now=now)
                return outcome

            set_key = _set_key(provenance)
            set_dir = cache / "sets" / set_key
            if (set_dir / "stamp.json").is_file():
                _prune_completed_sets(cache)
                outcome = _RustPrebuildConsumeOutcome(True, "hit", set_key=set_key)
                _write_last_result(cache, outcome, now=now)
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
                    run=runner,
                    which=which,
                )
                os.replace(tmp_dir, set_dir)
            except Exception:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                outcome = _miss(MISS_STAMP_MISSING)
                _write_last_result(cache, outcome, now=now)
                return outcome
            _prune_completed_sets(cache)
            outcome = _RustPrebuildConsumeOutcome(True, "hit", set_key=set_key)
            _write_last_result(cache, outcome, now=now)
            return outcome
        except Exception:
            log.debug("Rust prebuild producer failed", exc_info=True)
            outcome = _miss(MISS_STAMP_MISSING)
            _write_last_result(cache, outcome, now=now)
            return outcome


def _consume_prebuild(
    *,
    core_root: Path,
    host_root: Path,
    target_python: str,
    profile: str | None = None,
    root: Path | None = None,
    config: Mapping[str, Any] | None = None,
    run: CommandRunner | None = None,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> _RustPrebuildConsumeOutcome:
    """Install a matching prebuilt set, or return a precise miss reason."""
    if not _prebuild_enabled(config):
        return _miss(MISS_DISABLED)
    runner = run or _run_command
    active_profile = profile or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    commit = _resolve_commit(core_root, "HEAD", runner)
    if commit is None:
        return _miss(MISS_COMMIT_MISMATCH)
    provenance = _current_provenance(
        core_root,
        core_commit=commit,
        target_python=target_python,
        profile=active_profile,
        run=runner,
    )
    if provenance is None:
        return _miss(MISS_STAMP_MISSING)

    match = _find_matching_set(root or _cache_root(), provenance)
    if isinstance(match, _RustPrebuildConsumeOutcome):
        return match
    set_dir, stamp = match
    artifacts = _artifact_paths(set_dir, stamp)
    if artifacts is None:
        return _miss(MISS_STAMP_MISSING)
    extension_src, lsp_src = artifacts
    if not _stamp_digests_match(stamp, extension_src, lsp_src):
        return _miss(MISS_DIGEST_MISMATCH)
    try:
        _install_artifacts(
            extension_src,
            lsp_src,
            core_root=core_root,
            host_root=host_root,
            target_python=target_python,
            run=runner,
            replace_file=replace_file,
        )
    except OSError:
        return _miss(MISS_COPY_FAILURE)
    if not _probe_installed_extension(target_python, runner):
        return _miss(MISS_HEALTH_CHECK_FAILED)
    return _RustPrebuildConsumeOutcome(True, "hit", set_key=set_dir.name)


def _outcome_marker(outcome: _RustPrebuildConsumeOutcome) -> str:
    """Serialize a consume outcome for executor parsing."""
    return json.dumps(
        {
            PREBUILD_MARKER_KEY: {
                "hit": outcome.hit,
                "reason": outcome.reason,
                "set_key": outcome.set_key,
            }
        },
        sort_keys=True,
    )


def parse_outcome_marker(text: str) -> _RustPrebuildConsumeOutcome | None:
    """Parse the newest prebuild marker from command output."""
    for line in reversed(text.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        raw = payload.get(PREBUILD_MARKER_KEY)
        if not isinstance(raw, dict):
            continue
        hit = raw.get("hit")
        reason = raw.get("reason")
        set_key = raw.get("set_key")
        if isinstance(hit, bool) and isinstance(reason, str):
            return _RustPrebuildConsumeOutcome(
                hit=hit,
                reason=reason,
                set_key=set_key if isinstance(set_key, str) else None,
            )
    return None


def _miss(reason: str) -> _RustPrebuildConsumeOutcome:
    return _RustPrebuildConsumeOutcome(False, reason)


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


def _code_swap_writer_active() -> bool:
    """Best-effort non-blocking probe for the active update writer holder."""
    lock_path = sase_subdir("locks") / "code-swap.lock"
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not raw:
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return True
    return isinstance(payload, dict) and payload.get("op") == "dev.update"


def _resolve_commit(root: Path, ref: str, run: CommandRunner) -> str | None:
    result = run(("git", "-C", str(root), "rev-parse", f"{ref}^{{commit}}"))
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _live_checkout_still_behind(
    source_root: Path,
    upstream_ref: str,
    requested_commit: str,
    run: CommandRunner,
) -> bool:
    try:
        status = classify_git_upstream(source_root)
    except Exception:
        return False
    if not status.strictly_behind or status.upstream != upstream_ref:
        return False
    observed = _resolve_commit(
        Path(status.root),
        status.upstream or upstream_ref,
        run,
    )
    return observed == requested_commit


def _ensure_mirror(
    live_root: Path,
    mirror: Path,
    commit: str,
    run: CommandRunner,
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


def _current_provenance(
    core_root: Path,
    *,
    core_commit: str,
    target_python: str,
    profile: str,
    run: CommandRunner,
) -> _RustPrebuildProvenance | None:
    lock_sha = _sha256_file(core_root / "Cargo.lock")
    if lock_sha is None:
        return None
    rustc = run(("rustc", "--version"))
    if rustc.returncode != 0:
        return None
    identity = _python_identity(target_python, run)
    if identity is None:
        return None
    return _RustPrebuildProvenance(
        core_commit=core_commit,
        cargo_lock_sha256=lock_sha,
        rustc_version=rustc.stdout.strip(),
        profile=profile,
        target_interpreter=identity.executable,
        python_abi=identity.abi,
    )


def _python_identity(python: str, run: CommandRunner) -> _PythonIdentity | None:
    script = (
        "import json, sys, sysconfig; "
        "print(json.dumps({"
        "'executable': sys.executable, "
        "'abi': sysconfig.get_config_var('SOABI') or ''"
        "}))"
    )
    result = run((python, "-c", script))
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    executable = payload.get("executable")
    abi = payload.get("abi")
    if not isinstance(executable, str) or not isinstance(abi, str):
        return None
    return _PythonIdentity(executable=executable, abi=abi)


def _set_key(provenance: _RustPrebuildProvenance) -> str:
    raw = json.dumps(asdict(provenance), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _build_set(
    mirror: Path,
    set_dir: Path,
    provenance: _RustPrebuildProvenance,
    *,
    target_python: str,
    run: CommandRunner,
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
                "sha256": _sha256_file(extension_path),
            },
            "lsp": {
                "path": str(lsp_path.relative_to(set_dir)),
                "sha256": _sha256_file(lsp_path),
            },
        },
    }
    _atomic_write_json(set_dir / "stamp.json", stamp)


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


def _find_matching_set(
    root: Path,
    provenance: _RustPrebuildProvenance,
) -> tuple[Path, dict[str, Any]] | _RustPrebuildConsumeOutcome:
    stamps = _completed_stamps(root)
    if not stamps:
        return _miss(MISS_STAMP_MISSING)
    newest_reason = MISS_STAMP_MISSING
    for set_dir, stamp in stamps:
        mismatch = _provenance_mismatch(stamp, provenance)
        if mismatch is None:
            return set_dir, stamp
        if newest_reason == MISS_STAMP_MISSING:
            newest_reason = mismatch
    return _miss(newest_reason)


def _completed_stamps(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    sets_dir = root / "sets"
    try:
        candidates = [path for path in sets_dir.iterdir() if path.is_dir()]
    except OSError:
        return []
    stamps: list[tuple[Path, dict[str, Any]]] = []
    for set_dir in candidates:
        stamp_path = set_dir / "stamp.json"
        try:
            data = json.loads(stamp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION:
            stamps.append((set_dir, data))
    return sorted(
        stamps,
        key=lambda item: (item[0] / "stamp.json").stat().st_mtime,
        reverse=True,
    )


def _provenance_mismatch(
    stamp: Mapping[str, Any],
    provenance: _RustPrebuildProvenance,
) -> str | None:
    expected = asdict(provenance)
    for field, reason in _FIELD_MISMATCH_REASONS:
        if stamp.get(field) != expected[field]:
            return reason
    return None


def _artifact_paths(
    set_dir: Path,
    stamp: Mapping[str, Any],
) -> tuple[Path, Path] | None:
    artifacts = stamp.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    extension = artifacts.get("extension")
    lsp = artifacts.get("lsp")
    if not isinstance(extension, dict) or not isinstance(lsp, dict):
        return None
    extension_rel = extension.get("path")
    lsp_rel = lsp.get("path")
    if not isinstance(extension_rel, str) or not isinstance(lsp_rel, str):
        return None
    return set_dir / extension_rel, set_dir / lsp_rel


def _stamp_digests_match(
    stamp: Mapping[str, Any],
    extension: Path,
    lsp: Path,
) -> bool:
    artifacts = stamp.get("artifacts")
    if not isinstance(artifacts, dict):
        return False
    expected_ext = _artifact_sha(artifacts, "extension")
    expected_lsp = _artifact_sha(artifacts, "lsp")
    return (
        expected_ext is not None
        and expected_lsp is not None
        and _sha256_file(extension) == expected_ext
        and _sha256_file(lsp) == expected_lsp
    )


def _artifact_sha(artifacts: Mapping[str, Any], key: str) -> str | None:
    value = artifacts.get(key)
    if not isinstance(value, dict):
        return None
    digest = value.get("sha256")
    return digest if isinstance(digest, str) else None


def _install_artifacts(
    extension_src: Path,
    lsp_src: Path,
    *,
    core_root: Path,
    host_root: Path,
    target_python: str,
    run: CommandRunner,
    replace_file: Callable[[Path, Path], None],
) -> None:
    extension_dest = (
        core_root
        / "crates"
        / "sase_core_py"
        / "python"
        / "sase_core_rs"
        / EXTENSION_FILENAME
    )
    lsp_dest = Path(target_python).parent / LSP_BINARY_NAME
    _copy_atomic(extension_src, extension_dest, replace_file=replace_file)
    _copy_atomic(lsp_src, lsp_dest, executable=True, replace_file=replace_file)
    purge = host_root / "tools" / "purge_sase_core_rs_extensions"
    result = run((target_python, str(purge)))
    if result.returncode != 0:
        raise OSError(result.stderr or result.stdout or "extension purge failed")


def _copy_atomic(
    source: Path,
    destination: Path,
    *,
    executable: bool = False,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, tmp)
        if executable:
            tmp.chmod(tmp.stat().st_mode | 0o111)
        replace_file(tmp, destination)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _probe_installed_extension(target_python: str, run: CommandRunner) -> bool:
    result = run((target_python, "-c", "import sase_core_rs"))
    return result.returncode == 0


def _prebuild_enabled(config: Mapping[str, Any] | None) -> bool:
    data = load_merged_config() if config is None else config
    ace = data.get("ace") if isinstance(data, Mapping) else None
    updates = ace.get("updates") if isinstance(ace, Mapping) else None
    if not isinstance(updates, Mapping):
        return True
    value = updates.get("prebuild_rust")
    if isinstance(value, bool):
        return value
    return True


def _prune_completed_sets(root: Path) -> None:
    for set_dir, _stamp in _completed_stamps(root)[COMPLETED_SET_RETENTION:]:
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


def _write_last_result(
    root: Path,
    outcome: _RustPrebuildConsumeOutcome,
    *,
    now: Callable[[], float],
) -> None:
    payload = {
        "checked_at": now(),
        PREBUILD_MARKER_KEY: {
            "hit": outcome.hit,
            "reason": outcome.reason,
            "set_key": outcome.set_key,
        },
    }
    try:
        _atomic_write_json(root / "last-result.json", payload)
    except OSError:
        log.debug("Failed to write Rust prebuild diagnostic", exc_info=True)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> DevCommandResult:
    command_env = None if env is None else {**os.environ, **dict(env)}
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            env=command_env,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        return DevCommandResult(127, stderr=str(exc))
    except OSError as exc:
        return DevCommandResult(1, stderr=str(exc))
    return DevCommandResult(
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    produce = subparsers.add_parser("produce")
    produce.add_argument("--source-root", required=True)
    produce.add_argument("--upstream-ref", required=True)
    produce.add_argument("--python", required=True)
    produce.add_argument("--profile")
    consume = subparsers.add_parser("consume")
    consume.add_argument("--core-root", required=True)
    consume.add_argument("--host-root", required=True)
    consume.add_argument("--python", required=True)
    consume.add_argument("--profile")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "produce":
        _produce_prebuild(
            source_root=Path(args.source_root),
            upstream_ref=args.upstream_ref,
            target_python=args.python,
            profile=args.profile,
        )
        return 0
    outcome = _consume_prebuild(
        core_root=Path(args.core_root),
        host_root=Path(args.host_root),
        target_python=args.python,
        profile=args.profile,
    )
    print(_outcome_marker(outcome))
    return 0 if outcome.hit else 1


if __name__ == "__main__":
    raise SystemExit(main())
