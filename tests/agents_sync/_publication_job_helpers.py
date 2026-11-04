"""Shared public helpers for private publication job test modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import publication_job
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem


def publication_item(
    global_agent: str,
    revision: str,
    *,
    created_at: float,
    artifacts_dir: Path | str | None = None,
    run_id: str | None = None,
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=global_agent.rsplit(".", 1)[-1],
        global_agent=global_agent,
        primary_revision=revision,
        local_hood="hood",
        artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else None,
        run_id=run_id,
        created_at=created_at,
    )


def publication_target(tmp_path: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=tmp_path / "primary",
        primary_roots=(tmp_path / "primary",),
        sidecar_path=tmp_path / "agents",
        remote_url="https://example.invalid/agents.git",
    )


def configure_single_project_job(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
) -> None:
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj",
                workspace_dir=str(target.primary_checkout),
                is_project=True,
            )
        ],
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
    )


def publication_hint(global_agent: str, revision: str) -> dict[str, str]:
    return {
        "local_agent": "worker",
        "global_agent": global_agent,
        "primary_revision": revision,
        "run_id": "run-1",
        "link_outbox_agent_name": "",
    }
