"""Shared builders for ``sase chat`` handler tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.history.chat_catalog import ChatTranscriptInfo
from sase.history.chat_catalog_provenance import (
    CHAT_PROVENANCE_VALUES,
    ChatCatalogEntry,
    ChatCatalogSnapshot,
)

from tests.conftest import redirect_sase_home


def setup_fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    sase_home = tmp_path / ".sase"
    sase_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    redirect_sase_home(monkeypatch, sase_home)
    return sase_home


def write_chat(
    sase_home: Path,
    basename: str,
    *,
    workflow: str = "run",
    agent: str | None = None,
    prompt: str = "Hello",
    response: str = "World",
    shard: str = "202604",
) -> Path:
    chat_dir = sase_home / "chats" / shard
    chat_dir.mkdir(parents=True, exist_ok=True)
    path = chat_dir / f"{basename}.md"
    header = f"# Chat History - {workflow}"
    if agent:
        header += f" ({agent})"
    body = f"{header}\n\n## Prompt\n\n{prompt}\n\n## Response\n\n{response}\n"
    path.write_text(body, encoding="utf-8")
    return path


def chat_info(**overrides: Any) -> ChatTranscriptInfo:
    defaults: dict[str, Any] = {
        "path": "~/.sase/chats/202604/branch-run-260429_101500.md",
        "absolute_path": "/abs/branch-run-260429_101500.md",
        "basename": "branch-run-260429_101500",
        "mtime": "2026-04-29T10:15:08-04:00",
        "size_bytes": 123,
        "workflow": "run",
        "agent": None,
        "timestamp": "260429_101500",
        "prompt_snippet": "Hello there",
        "response_snippet": "World response",
    }
    defaults.update(overrides)
    return ChatTranscriptInfo(**defaults)


def catalog_entry(**overrides: Any) -> ChatCatalogEntry:
    defaults: dict[str, Any] = {
        "provenance": "local",
        "source_machine": "athena",
        "source_username": "alice",
        "project_key": "sase",
        "agent_artifact_dir": "/abs/artifacts/run/260429_101500",
        "agent_local_name": "alpha",
        "agent_global_name": "athena.alpha",
        "sidecar_repo": None,
        "sidecar_relpath": None,
        "publication_pending": False,
        "publication_last_error": None,
        "publication_quarantined": False,
        "publication_attempts": None,
        "publication_disposition": None,
    }
    provenance_keys = set(defaults)
    defaults.update({k: v for k, v in overrides.items() if k in provenance_keys})
    info = chat_info(**{k: v for k, v in overrides.items() if k not in provenance_keys})
    return ChatCatalogEntry(
        path=info.path,
        absolute_path=info.absolute_path,
        basename=info.basename,
        mtime=info.mtime,
        size_bytes=info.size_bytes,
        workflow=info.workflow,
        agent=info.agent,
        timestamp=info.timestamp,
        prompt_snippet=info.prompt_snippet,
        response_snippet=info.response_snippet,
        **defaults,
    )


def catalog_snapshot(entries: list[ChatCatalogEntry]) -> ChatCatalogSnapshot:
    return ChatCatalogSnapshot(
        entries=tuple(entries),
        provenance_counts={
            value: sum(e.provenance == value for e in entries)
            for value in CHAT_PROVENANCE_VALUES
        },
        remote_machines=frozenset(
            e.source_machine
            for e in entries
            if e.provenance == "remote" and e.source_machine
        ),
        truncated=False,
    )


def fake_catalog(entries: list[ChatCatalogEntry]) -> Any:
    """Build a ``load_chat_catalog`` stand-in that applies CLI-level filters."""
    calls: list[dict[str, Any]] = []

    def loader(**kwargs: Any) -> ChatCatalogSnapshot:
        calls.append(kwargs)
        provenance = kwargs.get("provenance")
        machine = kwargs.get("machine")
        limit = kwargs.get("limit")
        selected = [
            entry
            for entry in entries
            if (provenance is None or entry.provenance == provenance)
            and (
                machine is None
                or (
                    entry.source_machine is not None
                    and entry.source_machine.casefold() == machine.casefold()
                )
            )
        ]
        if limit is not None:
            selected = selected[:limit]
        return catalog_snapshot(selected)

    loader.calls = calls  # type: ignore[attr-defined]
    return loader
