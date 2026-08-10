"""Shared cache metadata and provenance helpers for Rust prebuilds."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.dev_update.models import DevCommandRunner, DevRustPrebuildResult

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


@dataclass(frozen=True)
class _PythonIdentity:
    """Resolved target interpreter details used in prebuild provenance."""

    executable: str
    abi: str


@dataclass(frozen=True)
class RustPrebuildProvenance:
    """Exact inputs that must match before a cached set can be installed."""

    core_commit: str
    cargo_lock_sha256: str
    rustc_version: str
    profile: str
    target_interpreter: str
    python_abi: str


@dataclass(frozen=True)
class RustPrebuildConsumeOutcome:
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


def outcome_marker(outcome: RustPrebuildConsumeOutcome) -> str:
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


def parse_outcome_marker(text: str) -> RustPrebuildConsumeOutcome | None:
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
            return RustPrebuildConsumeOutcome(
                hit=hit,
                reason=reason,
                set_key=set_key if isinstance(set_key, str) else None,
            )
    return None


def prebuild_miss(reason: str) -> RustPrebuildConsumeOutcome:
    return RustPrebuildConsumeOutcome(False, reason)


def resolve_commit(root: Path, ref: str, run: DevCommandRunner) -> str | None:
    result = run(("git", "-C", str(root), "rev-parse", f"{ref}^{{commit}}"))
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def current_provenance(
    core_root: Path,
    *,
    core_commit: str,
    target_python: str,
    profile: str,
    run: DevCommandRunner,
) -> RustPrebuildProvenance | None:
    lock_sha = sha256_file(core_root / "Cargo.lock")
    if lock_sha is None:
        return None
    rustc = run(("rustc", "--version"))
    if rustc.returncode != 0:
        return None
    identity = _python_identity(target_python, run)
    if identity is None:
        return None
    return RustPrebuildProvenance(
        core_commit=core_commit,
        cargo_lock_sha256=lock_sha,
        rustc_version=rustc.stdout.strip(),
        profile=profile,
        target_interpreter=identity.executable,
        python_abi=identity.abi,
    )


def _python_identity(
    python: str,
    run: DevCommandRunner,
) -> _PythonIdentity | None:
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


def prebuild_set_key(provenance: RustPrebuildProvenance) -> str:
    raw = json.dumps(asdict(provenance), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def find_matching_set(
    root: Path,
    provenance: RustPrebuildProvenance,
) -> tuple[Path, dict[str, Any]] | RustPrebuildConsumeOutcome:
    stamps = completed_stamps(root)
    if not stamps:
        return prebuild_miss(MISS_STAMP_MISSING)
    newest_reason = MISS_STAMP_MISSING
    for set_dir, stamp in stamps:
        mismatch = _provenance_mismatch(stamp, provenance)
        if mismatch is None:
            return set_dir, stamp
        if newest_reason == MISS_STAMP_MISSING:
            newest_reason = mismatch
    return prebuild_miss(newest_reason)


def completed_stamps(root: Path) -> list[tuple[Path, dict[str, Any]]]:
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
    provenance: RustPrebuildProvenance,
) -> str | None:
    expected = asdict(provenance)
    for field, reason in _FIELD_MISMATCH_REASONS:
        if stamp.get(field) != expected[field]:
            return reason
    return None


def artifact_paths(
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


def stamp_digests_match(
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
        and sha256_file(extension) == expected_ext
        and sha256_file(lsp) == expected_lsp
    )


def _artifact_sha(artifacts: Mapping[str, Any], key: str) -> str | None:
    value = artifacts.get(key)
    if not isinstance(value, dict):
        return None
    digest = value.get("sha256")
    return digest if isinstance(digest, str) else None


def write_last_result(
    root: Path,
    outcome: RustPrebuildConsumeOutcome,
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
        atomic_write_json(root / "last-result.json", payload)
    except OSError:
        log.debug("Failed to write Rust prebuild diagnostic", exc_info=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
