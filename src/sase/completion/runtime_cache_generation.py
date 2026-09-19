"""Transactional staging and publication for runtime grammar generations."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.completion.install_models import ExpectedCompletion, ZcompileFn
from sase.completion.install_scripts import (
    completion_payload,
    publish_script,
    zwc_freshness,
    zwc_path,
)
from sase.completion.runtime_cache_models import (
    CACHE_FORMAT_REVISION,
    CACHE_SCHEMA_VERSION,
    CompletionCacheError,
)
from sase.completion.runtime_cache_support import (
    grammar_filename,
    read_text,
    remove_tree,
    sha256_text,
)

_BACKUP_NAME = ".backup"
_STAGE_PREFIX = ".stage."


def commit_generation(
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
    *,
    replace_file: Callable[[Path, Path], None],
    write_manifest: Callable[..., None],
) -> None:
    """Stage and atomically publish a coherent grammar, bytecode, and manifest."""
    staging, backup = (
        directory / f"{_STAGE_PREFIX}{os.getpid()}",
        directory / _BACKUP_NAME,
    )
    remove_tree(staging)
    try:
        _stage(
            staging,
            grammar,
            shell,
            expected,
            identity,
            runtime_key,
            fingerprint,
            loader_target,
            owner,
            now,
            zcompile_fn,
            write_manifest,
        )
        had_backup = _backup(directory, backup, shell)
        try:
            _publish(staging, directory, shell, replace_file)
        except Exception:
            if had_backup:
                _restore(backup, directory)
            else:
                _remove_generation_files(directory, shell)
            raise
    except Exception as exc:
        remove_tree(staging)
        if coherent(directory, shell):
            remove_tree(backup)
        if isinstance(exc, CompletionCacheError):
            raise
        raise CompletionCacheError(str(exc)) from exc
    remove_tree(staging)
    remove_tree(backup)


def _stage(
    staging: Path,
    grammar: Path,
    shell: str,
    expected: ExpectedCompletion,
    identity: Mapping[str, Any],
    key: str,
    fingerprint: str,
    loader: Path | None,
    owner: str | None,
    now: datetime,
    zcompile_fn: ZcompileFn | None,
    write_manifest: Callable[..., None],
) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    try:
        publish_script(
            staging / grammar_filename(shell),
            expected.script,
            shell=shell,
            zcompile_fn=zcompile_fn,
        )
    except Exception as exc:
        raise CompletionCacheError(str(exc)) from exc
    write_manifest(
        staging / "manifest.json",
        shell=shell,
        runtime_key=key,
        identity=identity,
        fingerprint=fingerprint,
        grammar=grammar,
        expected=expected,
        payload=completion_payload(expected.script),
        loader_target=loader,
        owner=owner,
        now=now,
    )
    if not coherent(staging, shell):
        raise CompletionCacheError("staged completion generation is not coherent")
    data = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    if Path(str(data.get("grammar_path"))) != grammar.resolve(strict=False):
        raise CompletionCacheError(
            "staged manifest does not name the public grammar path"
        )


def _publish(
    staging: Path, directory: Path, shell: str, replace: Callable[[Path, Path], None]
) -> None:
    name = grammar_filename(shell)
    replace(staging / name, directory / name)
    if shell == "zsh":
        replace(zwc_path(staging / name), zwc_path(directory / name))
    replace(staging / "manifest.json", directory / "manifest.json")


def current_manifest(grammar: Path, shell: str, key: str, fingerprint: str) -> bool:
    try:
        data = json.loads(
            (grammar.parent / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("schema_version") == CACHE_SCHEMA_VERSION
        and data.get("cache_format_revision") == CACHE_FORMAT_REVISION
        and data.get("shell") == shell
        and data.get("runtime_key") == key
        and data.get("source_fingerprint") == fingerprint
        and (
            data.get("grammar_path") is None
            or Path(str(data["grammar_path"])) == grammar.resolve(strict=False)
        )
        and coherent(grammar.parent, shell)
    )


def write_manifest(
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
        "content_checksum": sha256_text(payload),
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
    manifest.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(tmp, manifest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def recover_interrupted_publish(directory: Path, shell: str) -> None:
    for child in directory.iterdir():
        if child.name.startswith(_STAGE_PREFIX):
            remove_tree(child)
    backup = directory / _BACKUP_NAME
    if coherent(directory, shell):
        remove_tree(backup)
    elif backup.is_dir() and coherent(backup, shell):
        _restore(backup, directory)
        remove_tree(backup)
    else:
        remove_tree(backup)
        _remove_generation_files(directory, shell)


def coherent(directory: Path, shell: str) -> bool:
    grammar = directory / grammar_filename(shell)
    try:
        data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    payload = read_text(grammar)
    return bool(
        isinstance(data, dict)
        and data.get("schema_version") == CACHE_SCHEMA_VERSION
        and data.get("cache_format_revision") == CACHE_FORMAT_REVISION
        and data.get("shell") == shell
        and payload is not None
        and data.get("content_checksum") == sha256_text(payload)
        and (shell != "zsh" or zwc_freshness(shell, grammar) == "fresh")
    )


def _backup(directory: Path, backup: Path, shell: str) -> bool:
    remove_tree(backup)
    if not coherent(directory, shell):
        return False
    backup.mkdir(parents=True)
    for path in _generation_paths(directory, shell):
        if path.is_file():
            shutil.copy2(path, backup / path.name)
    return True


def _restore(backup: Path, directory: Path) -> None:
    try:
        for child in backup.iterdir():
            if child.is_file():
                os.replace(child, directory / child.name)
    except OSError as exc:
        raise CompletionCacheError(
            f"cannot restore completion cache backup: {exc}"
        ) from exc


def _generation_paths(directory: Path, shell: str) -> tuple[Path, ...]:
    grammar = directory / grammar_filename(shell)
    return (
        (grammar, zwc_path(grammar), directory / "manifest.json")
        if shell == "zsh"
        else (grammar, directory / "manifest.json")
    )


def _remove_generation_files(directory: Path, shell: str) -> None:
    for path in _generation_paths(directory, shell):
        try:
            path.unlink()
        except OSError:
            pass
