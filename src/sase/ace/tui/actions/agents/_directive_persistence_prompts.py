"""Prompt-artifact rewrites for worker-safe directive persistence."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sase.history.prompt_store import PromptHistoryLoadError, rewrite_prompt_text_exact

from ._directive_persistence_models import AgentDirectivePersistenceResult


def persist_prompt_artifacts(
    artifacts_path: Path,
    prompt_mutator: Callable[[str], str],
) -> AgentDirectivePersistenceResult:
    """Rewrite prompt artifacts, history, and stash for a prompt mutation."""
    from sase.legacy_xprompt_names import (
        LEGACY_RAW_XPROMPT_FILENAME,
        LEGACY_SUBMITTED_XPROMPT_FILENAME,
        RAW_PROMPT_FILENAME,
        SUBMITTED_PROMPT_FILENAME,
        resolve_artifact_path,
    )

    raw_path = resolve_artifact_path(
        artifacts_path, RAW_PROMPT_FILENAME, LEGACY_RAW_XPROMPT_FILENAME
    )
    if raw_path is None:
        return AgentDirectivePersistenceResult()
    try:
        old_prompt = raw_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AgentDirectivePersistenceResult()

    new_prompt = prompt_mutator(old_prompt)
    if new_prompt == old_prompt:
        return AgentDirectivePersistenceResult()

    _write_text_atomic(raw_path, new_prompt)

    submitted_updated = False
    submitted_path = resolve_artifact_path(
        artifacts_path, SUBMITTED_PROMPT_FILENAME, LEGACY_SUBMITTED_XPROMPT_FILENAME
    )
    try:
        submitted_prompt = (
            submitted_path.read_text(encoding="utf-8")
            if submitted_path is not None
            else None
        )
    except FileNotFoundError:
        submitted_prompt = None
    if submitted_path is not None and submitted_prompt == old_prompt:
        _write_text_atomic(submitted_path, new_prompt)
        submitted_updated = True

    try:
        history_rewrites = rewrite_prompt_text_exact(old_prompt, new_prompt)
    except PromptHistoryLoadError:
        history_rewrites = 0
    stash_rewrites = _rewrite_prompt_stash_exact(old_prompt, new_prompt)
    return AgentDirectivePersistenceResult(
        raw_prompt_updated=True,
        submitted_prompt_updated=submitted_updated,
        history_rewrites=history_rewrites,
        stash_rewrites=stash_rewrites,
    )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _rewrite_prompt_stash_exact(old_prompt: str, new_prompt: str) -> int:
    try:
        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            read_prompt_stash_snapshot,
            rewrite_prompt_stash,
        )

        path = prompt_stash_path()
        snapshot = read_prompt_stash_snapshot(path)
        replacements = [
            replace(entry, text=new_prompt)
            for entry in snapshot.entries
            if entry.text == old_prompt
        ]
        if not replacements:
            return 0
        rewrite_prompt_stash(path, replacements)
        return len(replacements)
    except Exception:
        return 0


__all__ = [
    "persist_prompt_artifacts",
]
