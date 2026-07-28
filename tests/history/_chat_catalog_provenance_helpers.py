"""Shared builders for chat catalog provenance tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.history.chat_catalog_provenance import artifacts, catalog

from tests.conftest import redirect_sase_home


def _setup_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / ".sase"
    home.mkdir()
    redirect_sase_home(monkeypatch, home)
    owner = AgentOwnerIdentity("bryan", "athena")
    monkeypatch.setattr(catalog, "get_agent_owner_identity", lambda: owner)
    monkeypatch.setattr(artifacts, "get_agent_owner_identity", lambda: owner)
    return home


def _chat(home: Path, name: str, *, prompt: str = "hello") -> Path:
    path = home / "chats" / "202607" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Chat History - ace-run (alpha)\n\n"
            f"## Prompt\n\n{prompt}\n\n"
            "## Response\n\ndone\n"
        ),
        encoding="utf-8",
    )
    return path


def _artifact(
    home: Path,
    timestamp: str,
    chat_path: Path,
    *,
    name: str = "alpha",
    meta_extra: dict[str, object] | None = None,
    done_extra: dict[str, object] | None = None,
) -> Path:
    path = home / "projects" / "proj" / "artifacts" / "ace-run" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": name, "chat_path": str(chat_path)}
    meta.update(meta_extra or {})
    done: dict[str, object] = {
        "name": name,
        "response_path": str(chat_path),
        "finished_at": 1.0,
    }
    done.update(done_extra or {})
    (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (path / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return path


def _selection(sidecar_path: Path) -> TargetSelection:
    target = ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=sidecar_path.parent / "primary",
        primary_roots=(),
        sidecar_path=sidecar_path,
        remote_url="git@example.invalid:agents.git",
    )
    return TargetSelection((target,), ())


def _readable_sidecar(path: Path) -> Path:
    agents = path / "agents"
    agents.mkdir(parents=True)
    return agents


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_sidecar(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(
        path,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    return path


def _commit_sidecar(path: Path, message: str = "publish") -> None:
    _git(path, "add", "-A")
    _git(
        path,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase@example.invalid",
        "commit",
        "-qm",
        message,
    )


def _publication_row(
    *,
    revision: str = "a" * 40,
    local_agent: str = "alpha",
    global_agent: str = "bryan.athena.alpha",
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    terminal: bool = False,
    terminal_reason: str | None = None,
    created_at: float = 1.0,
    updated_at: float = 1.0,
) -> dict[str, object]:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=local_agent,
        global_agent=global_agent,
        primary_revision=revision,
        local_hood=local_agent.split(".", 1)[0],
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=updated_at if quarantined else None,
        terminal=terminal,
        terminal_reason=terminal_reason,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def _write_outbox(
    home: Path,
    rows: list[dict[str, object]],
    *,
    schema_version: int = 2,
) -> Path:
    path = home / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": schema_version, "items": rows}),
        encoding="utf-8",
    )
    return path
