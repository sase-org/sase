"""Runtime grammar cache for installed shell-completion loaders."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import sase
from sase.completion.install_models import ExpectedCompletion, ExpectedFn, ZcompileFn
from sase.completion.install_scripts import (
    completion_payload,
    expected_scripts_for_shells,
    publish_script,
    zwc_freshness,
)
from sase.completion.install_targets import SUPPORTED_SHELLS, script_path
from sase.core.paths import sase_subdir

CACHE_SCHEMA_VERSION = 1
CACHE_FORMAT_REVISION = 1
LOCK_TIMEOUT_SECONDS = 10.0
_RUNTIME_CACHE_KEEP = 6
_DISTRIBUTIONS = ("sase", "sase-core-rs")


class CompletionCacheError(RuntimeError):
    """User-facing failure while resolving the runtime grammar cache."""


def ensure_cached_grammar(
    shell: str,
    *,
    force: bool = False,
    loader_path: str | Path | None = None,
    owner: str | None = None,
    target: str | Path | None = None,
    expected_fn: ExpectedFn | None = None,
    zcompile_fn: ZcompileFn | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> Path:
    """Return an absolute path to current cached grammar for *shell*.

    Warm calls only inspect the cache manifest and a lightweight source-stat
    fingerprint. They do not import the argparse parser, TUI, or command
    handlers. Misses build the parser once through ``expected_scripts_for_shells``.
    """
    if shell not in SUPPORTED_SHELLS:
        raise CompletionCacheError(f"unsupported shell: {shell}")
    if owner is not None and owner not in {"local", "chezmoi"}:
        raise CompletionCacheError(f"unsupported completion owner: {owner}")
    if loader_path is not None and target is not None:
        raise CompletionCacheError("pass either --loader-path or --target, not both")

    resolved_target = _loader_target(shell, loader_path=loader_path, target=target)
    identity = _runtime_identity()
    fingerprint = _source_fingerprint()
    runtime_key = _runtime_identity_key(identity)
    directory = _shell_cache_dir(runtime_key, shell)
    grammar = directory / _grammar_filename(shell)
    manifest = directory / "manifest.json"

    current = _read_current_manifest(
        manifest,
        shell=shell,
        runtime_key=runtime_key,
        fingerprint=fingerprint,
        grammar=grammar,
    )
    if current is not None and not force:
        return grammar.resolve(strict=False)

    directory.mkdir(parents=True, exist_ok=True)
    with _bounded_lock(directory / ".generate.lock"):
        current = _read_current_manifest(
            manifest,
            shell=shell,
            runtime_key=runtime_key,
            fingerprint=fingerprint,
            grammar=grammar,
        )
        if current is not None and not force:
            return grammar.resolve(strict=False)
        expected = _expected_for_shell(shell, expected_fn=expected_fn)
        payload = completion_payload(expected.script)
        try:
            publish_script(
                grammar,
                expected.script,
                shell=shell,
                zcompile_fn=zcompile_fn,
            )
        except Exception as exc:
            raise CompletionCacheError(str(exc)) from exc
        _write_manifest(
            manifest,
            shell=shell,
            runtime_key=runtime_key,
            identity=identity,
            fingerprint=fingerprint,
            grammar=grammar,
            expected=expected,
            payload=payload,
            loader_target=resolved_target,
            owner=owner,
            now=(now_fn or _utc_now)(),
        )
        _prune_old_runtime_dirs(_cache_root())
    return grammar.resolve(strict=False)


def _runtime_identity() -> dict[str, Any]:
    """Return installation identity used to partition grammar caches."""
    package_file = Path(sase.__file__).resolve(strict=False)
    package_root = package_file.parent
    return {
        "cache_format_revision": CACHE_FORMAT_REVISION,
        "distributions": _distribution_records(),
        "package_file": _path_record(package_file),
        "package_root": _path_record(package_root),
        "python_executable": _path_record(Path(sys.executable)),
        "python_version": sys.version.split()[0],
        "sase_version": sase.__version__,
    }


def _runtime_identity_key(identity: Mapping[str, Any] | None = None) -> str:
    """Return a stable directory key for one installed SASE runtime."""
    payload = identity if identity is not None else _runtime_identity()
    return _digest_json(payload)[:24]


def _source_fingerprint() -> str:
    """Return a conservative source-change fingerprint for CLI grammar inputs."""
    package_root = Path(sase.__file__).resolve(strict=False).parent
    roots = (
        package_root / "__init__.py",
        package_root / "completion",
        package_root / "main",
    )
    files: list[dict[str, object]] = []
    for root in roots:
        if root.is_file():
            files.append(_source_file_record(root, package_root=package_root))
            continue
        if not root.is_dir():
            files.append({"missing": _rel(root, package_root)})
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                files.append(_source_file_record(path, package_root=package_root))
    return _digest_json(
        {
            "cache_format_revision": CACHE_FORMAT_REVISION,
            "environment": _grammar_environment(),
            "files": files,
        }
    )


def _loader_target_from_dir(shell: str, target: str | Path) -> Path:
    """Return the loader file path implied by an install target directory."""
    return script_path(Path(target).expanduser(), shell)


def _expected_for_shell(
    shell: str, *, expected_fn: ExpectedFn | None
) -> ExpectedCompletion:
    expected = (expected_fn or expected_scripts_for_shells)((shell,))
    try:
        return expected[shell]
    except KeyError:
        raise CompletionCacheError(
            f"generator did not return {shell} completion"
        ) from None


def _read_current_manifest(
    manifest: Path,
    *,
    shell: str,
    runtime_key: str,
    fingerprint: str,
    grammar: Path,
) -> dict[str, Any] | None:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if data.get("cache_format_revision") != CACHE_FORMAT_REVISION:
        return None
    if data.get("shell") != shell:
        return None
    if data.get("runtime_key") != runtime_key:
        return None
    if data.get("source_fingerprint") != fingerprint:
        return None
    recorded = data.get("grammar_path")
    if recorded is not None and Path(str(recorded)) != grammar.resolve(strict=False):
        return None
    payload = _read_text(grammar)
    if payload is None:
        return None
    if data.get("content_checksum") != _sha256_text(payload):
        return None
    if shell == "zsh" and zwc_freshness(shell, grammar) != "fresh":
        return None
    return data


def _write_manifest(
    manifest: Path,
    *,
    shell: str,
    runtime_key: str,
    identity: Mapping[str, Any],
    fingerprint: str,
    grammar: Path,
    expected: ExpectedCompletion,
    payload: str,
    loader_target: Path | None,
    owner: str | None,
    now: datetime,
) -> None:
    data: dict[str, Any] = {
        "cache_format_revision": CACHE_FORMAT_REVISION,
        "content_checksum": _sha256_text(payload),
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "grammar_path": str(grammar.resolve(strict=False)),
        "runtime_identity": dict(identity),
        "runtime_key": runtime_key,
        "schema_version": CACHE_SCHEMA_VERSION,
        "shell": shell,
        "source_fingerprint": fingerprint,
        "structural_digest": expected.digest,
    }
    if loader_target is not None or owner is not None:
        data["loader"] = {
            "owner": owner,
            "target": None
            if loader_target is None
            else str(loader_target.expanduser().resolve(strict=False)),
        }
    _atomic_write_json(manifest, data)


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


@contextmanager
def _bounded_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CompletionCacheError(
                        f"timed out waiting for completion cache lock: {path}"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _prune_old_runtime_dirs(root: Path) -> None:
    try:
        entries = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return
    if len(entries) <= _RUNTIME_CACHE_KEEP:
        return
    entries.sort(key=lambda path: _mtime(path), reverse=True)
    for stale in entries[_RUNTIME_CACHE_KEEP:]:
        _remove_tree(stale)


def _remove_tree(path: Path) -> None:
    for child in sorted(
        path.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        try:
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _loader_target(
    shell: str,
    *,
    loader_path: str | Path | None,
    target: str | Path | None,
) -> Path | None:
    if loader_path is not None:
        return Path(loader_path).expanduser()
    if target is not None:
        return _loader_target_from_dir(shell, target)
    return None


def _shell_cache_dir(runtime_key: str, shell: str) -> Path:
    return _cache_root() / runtime_key / shell


def _cache_root() -> Path:
    return sase_subdir("completion") / "grammar"


def _grammar_filename(shell: str) -> str:
    if shell == "bash":
        return "sase.bash"
    if shell == "fish":
        return "sase.fish"
    if shell == "zsh":
        return "_sase"
    raise CompletionCacheError(f"unsupported shell: {shell}")


def _distribution_records() -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for name in _DISTRIBUTIONS:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            records.append({"name": name, "missing": True})
            continue
        records.append(
            {
                "location": str(Path(str(dist.locate_file(""))).resolve(strict=False)),
                "metadata_name": dist.metadata.get("Name", name),
                "name": name,
                "version": dist.version,
            }
        )
    return tuple(records)


def _grammar_environment() -> dict[str, str | None]:
    return {
        # SASE_HOME determines where this cache is stored, but not the generated
        # grammar bytes. It is still recorded so diagnostics can explain why two
        # otherwise identical invocations used different state roots.
        "SASE_HOME": os.environ.get("SASE_HOME"),
    }


def _source_file_record(path: Path, *, package_root: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"missing": _rel(path, package_root)}
    return {
        "mtime_ns": stat.st_mtime_ns,
        "path": _rel(path, package_root),
        "size": stat.st_size,
    }


def _path_record(path: Path) -> dict[str, object]:
    expanded = path.expanduser().resolve(strict=False)
    record: dict[str, object] = {"path": str(expanded)}
    try:
        stat = expanded.stat()
    except OSError:
        record["missing"] = True
    else:
        record.update(
            {
                "device": stat.st_dev,
                "inode": stat.st_ino,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
        )
    return record


def _rel(path: Path, package_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(package_root).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _digest_json(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CACHE_FORMAT_REVISION",
    "CACHE_SCHEMA_VERSION",
    "CompletionCacheError",
    "ensure_cached_grammar",
]
