"""Runtime grammar cache for installed shell-completion loaders."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
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
    zwc_path,
)
from sase.completion.install_targets import SUPPORTED_SHELLS, script_path
from sase.core.paths import sase_subdir

CACHE_SCHEMA_VERSION = 1
CACHE_FORMAT_REVISION = 1
LOCK_TIMEOUT_SECONDS = 10.0
_RUNTIME_CACHE_KEEP = 6
_DISTRIBUTIONS = ("sase", "sase-core-rs")
_BACKUP_NAME = ".backup"
_STAGE_PREFIX = ".stage."


class CompletionCacheError(RuntimeError):
    """User-facing failure while resolving the runtime grammar cache."""


@dataclass(frozen=True, slots=True)
class RuntimeGrammarStatus:
    """Read-only assessment of one shell's runtime grammar cache."""

    shell: str
    status: str
    path: str | None
    structural_digest: str | None
    drift_reasons: tuple[str, ...] = ()


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
        _recover_interrupted_publish(directory, shell=shell)
        current = _read_current_manifest(
            manifest,
            shell=shell,
            runtime_key=runtime_key,
            fingerprint=fingerprint,
            grammar=grammar,
        )
        if current is not None and not force:
            return grammar.resolve(strict=False)
        try:
            expected = _expected_for_shell(shell, expected_fn=expected_fn)
        except CompletionCacheError:
            raise
        except Exception as exc:
            raise CompletionCacheError(str(exc)) from exc
        _commit_generation(
            directory=directory,
            shell=shell,
            grammar=grammar,
            expected=expected,
            identity=identity,
            runtime_key=runtime_key,
            fingerprint=fingerprint,
            loader_target=resolved_target,
            owner=owner,
            now=(now_fn or _utc_now)(),
            zcompile_fn=zcompile_fn,
        )
        _prune_old_runtime_dirs(_cache_root())
    return grammar.resolve(strict=False)


def assess_cached_grammar(
    shell: str,
    *,
    expected: ExpectedCompletion | None = None,
) -> RuntimeGrammarStatus:
    """Return a read-only freshness assessment for *shell*'s cached grammar."""
    if shell not in SUPPORTED_SHELLS:
        raise CompletionCacheError(f"unsupported shell: {shell}")
    identity = _runtime_identity()
    fingerprint = _source_fingerprint()
    runtime_key = _runtime_identity_key(identity)
    directory = _shell_cache_dir(runtime_key, shell)
    grammar = directory / _grammar_filename(shell)
    manifest = directory / "manifest.json"
    path = str(grammar.resolve(strict=False))
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return RuntimeGrammarStatus(
            shell,
            "missing",
            path,
            None,
            ("runtime grammar cache manifest is missing",),
        )
    except json.JSONDecodeError:
        return RuntimeGrammarStatus(
            shell,
            "corrupt",
            path,
            None,
            ("runtime grammar cache manifest is not valid JSON",),
        )
    except OSError as exc:
        return RuntimeGrammarStatus(
            shell,
            "missing",
            path,
            None,
            (f"runtime grammar cache manifest cannot be read: {exc}",),
        )
    if not isinstance(data, dict):
        return RuntimeGrammarStatus(
            shell,
            "corrupt",
            path,
            None,
            ("runtime grammar cache manifest is not an object",),
        )

    reasons: list[str] = []
    status = "current"
    if data.get("schema_version") != CACHE_SCHEMA_VERSION:
        status = "stale"
        reasons.append("runtime grammar manifest schema is stale")
    if data.get("cache_format_revision") != CACHE_FORMAT_REVISION:
        status = "stale"
        reasons.append("runtime grammar cache format is stale")
    if data.get("shell") != shell:
        status = "corrupt"
        reasons.append("runtime grammar manifest shell does not match")
    if data.get("runtime_key") != runtime_key:
        status = "stale"
        reasons.append("runtime grammar runtime identity is stale")
    if data.get("source_fingerprint") != fingerprint:
        status = "stale"
        reasons.append("runtime grammar source fingerprint is stale")
    recorded = data.get("grammar_path")
    if recorded is not None and Path(str(recorded)) != grammar.resolve(strict=False):
        status = "stale"
        reasons.append("runtime grammar manifest points at another path")

    structural_digest = (
        None
        if data.get("structural_digest") is None
        else str(data["structural_digest"])
    )
    if expected is not None and structural_digest != expected.digest:
        status = "stale"
        reasons.append(
            "runtime grammar digest "
            f"{structural_digest or '<missing>'} differs from running "
            f"{expected.digest}"
        )

    payload = _read_text(grammar)
    if payload is None:
        status = "missing" if status == "current" else status
        reasons.append("runtime grammar file is missing or unreadable")
    elif data.get("content_checksum") != _sha256_text(payload):
        status = "corrupt"
        reasons.append("runtime grammar checksum does not match manifest")

    if shell == "zsh":
        grammar_zwc = zwc_freshness(shell, grammar)
        if grammar_zwc != "fresh":
            status = "zwc stale" if status == "current" else status
            reasons.append(f"runtime grammar .zwc is {grammar_zwc}")

    return RuntimeGrammarStatus(
        shell=shell,
        status=status,
        path=path,
        structural_digest=structural_digest,
        drift_reasons=tuple(reasons),
    )


def _commit_generation(
    *,
    directory: Path,
    shell: str,
    grammar: Path,
    expected: ExpectedCompletion,
    identity: Mapping[str, Any],
    runtime_key: str,
    fingerprint: str,
    loader_target: Path | None,
    owner: str | None,
    now: datetime,
    zcompile_fn: ZcompileFn | None,
) -> None:
    """Stage, validate, and publish one coherent generation.

    Live grammar, bytecode, and manifest are replaced only after the staged
    set is valid. A failure restores the previous coherent generation, or
    leaves no generation that can be mistaken for current.
    """
    staging = directory / f"{_STAGE_PREFIX}{os.getpid()}"
    backup = directory / _BACKUP_NAME
    _remove_tree(staging)
    published = False
    try:
        _stage_generation(
            staging=staging,
            live_grammar=grammar,
            shell=shell,
            expected=expected,
            identity=identity,
            runtime_key=runtime_key,
            fingerprint=fingerprint,
            loader_target=loader_target,
            owner=owner,
            now=now,
            zcompile_fn=zcompile_fn,
        )
        had_backup = _backup_live_generation(directory, backup, shell=shell)
        try:
            _publish_staged_generation(staging, directory, shell=shell)
            published = True
        except Exception:
            if had_backup:
                _restore_backup(backup, directory)
            else:
                _remove_generation_files(directory, shell)
            raise
    except Exception as exc:
        _remove_tree(staging)
        if _generation_is_coherent(directory, shell):
            _remove_tree(backup)
        if isinstance(exc, CompletionCacheError):
            raise
        raise CompletionCacheError(str(exc)) from exc
    if published:
        _remove_tree(staging)
        _remove_tree(backup)


def _stage_generation(
    *,
    staging: Path,
    live_grammar: Path,
    shell: str,
    expected: ExpectedCompletion,
    identity: Mapping[str, Any],
    runtime_key: str,
    fingerprint: str,
    loader_target: Path | None,
    owner: str | None,
    now: datetime,
    zcompile_fn: ZcompileFn | None,
) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    staged_grammar = staging / _grammar_filename(shell)
    payload = completion_payload(expected.script)
    try:
        publish_script(
            staged_grammar,
            expected.script,
            shell=shell,
            zcompile_fn=zcompile_fn,
        )
    except Exception as exc:
        raise CompletionCacheError(str(exc)) from exc
    _write_manifest(
        staging / "manifest.json",
        shell=shell,
        runtime_key=runtime_key,
        identity=identity,
        fingerprint=fingerprint,
        grammar=live_grammar,
        expected=expected,
        payload=payload,
        loader_target=loader_target,
        owner=owner,
        now=now,
    )
    if not _generation_is_coherent(staging, shell):
        raise CompletionCacheError("staged completion generation is not coherent")
    recorded = json.loads((staging / "manifest.json").read_text(encoding="utf-8")).get(
        "grammar_path"
    )
    if recorded is None or Path(str(recorded)) != live_grammar.resolve(strict=False):
        raise CompletionCacheError(
            "staged manifest does not name the public grammar path"
        )


def _publish_staged_generation(staging: Path, directory: Path, *, shell: str) -> None:
    name = _grammar_filename(shell)
    _replace_file(staging / name, directory / name)
    if shell == "zsh":
        _replace_file(zwc_path(staging / name), zwc_path(directory / name))
    _replace_file(staging / "manifest.json", directory / "manifest.json")


def _replace_file(src: Path, dst: Path) -> None:
    os.replace(src, dst)


def _backup_live_generation(directory: Path, backup: Path, *, shell: str) -> bool:
    _remove_tree(backup)
    if not _generation_is_coherent(directory, shell):
        return False
    backup.mkdir(parents=True)
    for path in _generation_paths(directory, shell):
        if path.is_file():
            shutil.copy2(path, backup / path.name)
    return True


def _restore_backup(backup: Path, directory: Path) -> None:
    try:
        children = list(backup.iterdir())
    except OSError as exc:
        raise CompletionCacheError(
            f"cannot restore completion cache backup: {exc}"
        ) from exc
    for child in children:
        if child.is_file():
            os.replace(child, directory / child.name)


def _recover_interrupted_publish(directory: Path, *, shell: str) -> None:
    _cleanup_staging(directory)
    backup = directory / _BACKUP_NAME
    live_ok = _generation_is_coherent(directory, shell)
    backup_ok = backup.is_dir() and _generation_is_coherent(backup, shell)
    if live_ok:
        if backup.exists():
            _remove_tree(backup)
        return
    if backup_ok:
        _restore_backup(backup, directory)
        _remove_tree(backup)
        return
    if backup.exists():
        _remove_tree(backup)
    _remove_generation_files(directory, shell)


def _cleanup_staging(directory: Path) -> None:
    try:
        children = list(directory.iterdir())
    except OSError:
        return
    for child in children:
        if child.name.startswith(_STAGE_PREFIX):
            _remove_tree(child)


def _generation_paths(directory: Path, shell: str) -> tuple[Path, ...]:
    grammar = directory / _grammar_filename(shell)
    paths = [grammar, directory / "manifest.json"]
    if shell == "zsh":
        paths.append(zwc_path(grammar))
    return tuple(paths)


def _remove_generation_files(directory: Path, shell: str) -> None:
    for path in _generation_paths(directory, shell):
        try:
            path.unlink()
        except OSError:
            pass


def _generation_is_coherent(directory: Path, shell: str) -> bool:
    grammar = directory / _grammar_filename(shell)
    try:
        data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") != CACHE_SCHEMA_VERSION:
        return False
    if data.get("cache_format_revision") != CACHE_FORMAT_REVISION:
        return False
    if data.get("shell") != shell:
        return False
    payload = _read_text(grammar)
    if payload is None:
        return False
    if data.get("content_checksum") != _sha256_text(payload):
        return False
    return shell != "zsh" or zwc_freshness(shell, grammar) == "fresh"


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
    "RuntimeGrammarStatus",
    "assess_cached_grammar",
    "ensure_cached_grammar",
]
