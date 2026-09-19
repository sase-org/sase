"""Runtime grammar cache public API and generation orchestration."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.completion.install_models import ExpectedCompletion, ExpectedFn, ZcompileFn
from sase.completion.install_targets import SUPPORTED_SHELLS, script_path
from sase.completion.runtime_cache_generation import commit_generation, current_manifest
from sase.completion.runtime_cache_identity import (
    runtime_identity as _runtime_identity,
    runtime_identity_key as _runtime_identity_key,
    source_fingerprint as _source_fingerprint,
)
from sase.completion.runtime_cache_models import (
    CACHE_FORMAT_REVISION,
    CACHE_SCHEMA_VERSION,
    CompletionCacheError,
    RuntimeGrammarStatus,
)
from sase.completion.runtime_cache_status import assess_cached_grammar as _assess
from sase.completion.runtime_cache_support import (
    bounded_lock,
    cache_root,
    grammar_filename,
    prune_old_runtime_dirs,
    shell_cache_dir,
)


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
    """Return the current cached grammar path for *shell*."""
    if shell not in SUPPORTED_SHELLS:
        raise CompletionCacheError(f"unsupported shell: {shell}")
    if owner is not None and owner not in {"local", "chezmoi"}:
        raise CompletionCacheError(f"unsupported completion owner: {owner}")
    if loader_path is not None and target is not None:
        raise CompletionCacheError("pass either --loader-path or --target, not both")
    loader_target = _loader_target(shell, loader_path, target)
    identity, fingerprint = _runtime_identity(), _source_fingerprint()
    key = _runtime_identity_key(identity)
    directory = shell_cache_dir(key, shell)
    grammar = directory / grammar_filename(shell)
    if not force and current_manifest(grammar, shell, key, fingerprint):
        return grammar.resolve(strict=False)
    directory.mkdir(parents=True, exist_ok=True)
    with bounded_lock(directory / ".generate.lock"):
        from sase.completion.runtime_cache_generation import recover_interrupted_publish

        recover_interrupted_publish(directory, shell)
        if not force and current_manifest(grammar, shell, key, fingerprint):
            return grammar.resolve(strict=False)
        try:
            expected = _expected_for_shell(shell, expected_fn)
            commit_generation(
                directory,
                shell,
                grammar,
                expected,
                identity,
                key,
                fingerprint,
                loader_target,
                owner,
                (now_fn or _utc_now)(),
                zcompile_fn,
                replace_file=_replace_file,
                write_manifest=_write_manifest,
            )
        except CompletionCacheError:
            raise
        except Exception as exc:
            raise CompletionCacheError(str(exc)) from exc
        prune_old_runtime_dirs(cache_root())
    return grammar.resolve(strict=False)


def assess_cached_grammar(
    shell: str, *, expected: ExpectedCompletion | None = None
) -> RuntimeGrammarStatus:
    """Return a read-only freshness assessment for *shell*'s cached grammar."""
    identity = _runtime_identity()
    key = _runtime_identity_key(identity)
    grammar = shell_cache_dir(key, shell) / grammar_filename(shell)
    return _assess(
        shell,
        runtime_key=key,
        fingerprint=_source_fingerprint(),
        grammar=grammar,
        expected=expected,
    )


def _expected_for_shell(
    shell: str, expected_fn: ExpectedFn | None
) -> ExpectedCompletion:
    from sase.completion.install_scripts import expected_scripts_for_shells

    try:
        return (expected_fn or expected_scripts_for_shells)((shell,))[shell]
    except KeyError:
        raise CompletionCacheError(
            f"generator did not return {shell} completion"
        ) from None


def _loader_target(
    shell: str, loader_path: str | Path | None, target: str | Path | None
) -> Path | None:
    if loader_path is not None:
        return Path(loader_path).expanduser()
    return None if target is None else script_path(Path(target).expanduser(), shell)


def _replace_file(src: Path, dst: Path) -> None:
    os.replace(src, dst)


def _write_manifest(*args: Any, **kwargs: Any) -> None:
    from sase.completion.runtime_cache_generation import write_manifest

    write_manifest(*args, **kwargs)


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
