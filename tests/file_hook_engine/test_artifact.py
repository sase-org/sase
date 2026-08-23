"""Artifact-time file-hook engine tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.create import handle_create
from sase.core.artifact_file_types import ArtifactFile
from sase.file_hooks.audit import list_file_hook_audits
from sase.file_hooks.engine import (
    capture_artifact_file_event,
    emit_artifact_file_hook_event,
)
from sase.notifications.priority import is_error
from sase.notifications.store import load_notifications

from .helpers import (
    clear_agent_env,
    emitted_agent_names,
    event,
    hook,
    init_repo,
    stub_detached_spawn,
)


def test_artifact_capture_and_emit_preserve_the_agent_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    source = repo / "report.md"
    source.write_text("# report\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    stored.write_text("# report\n", encoding="utf-8")
    clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.final")
    monkeypatch.setattr(
        "sase.file_hooks.engine.get_all_file_hooks",
        lambda: [hook("render")],
    )
    stub_detached_spawn(monkeypatch)

    captured = capture_artifact_file_event(source)
    assert captured.agent_name == "research.7.final"

    batch_path = emit_artifact_file_hook_event(captured, stored)

    assert batch_path is not None
    assert emitted_agent_names(batch_path) == ["research.7.final"]


def test_artifact_capture_outside_a_repo_matches_just_the_basename(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside.md"
    source.write_text("# outside\n", encoding="utf-8")

    captured = capture_artifact_file_event(source)

    assert captured.abs_path == str(source)
    assert captured.repo_root == str(tmp_path)
    assert captured.rel_path == "outside.md"
    assert captured.repo_kind == "external:untracked"
    assert captured.sidecar_role is None
    assert captured.op == "ADD"


def test_artifact_create_emits_stored_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# source\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    stored.write_text("# source\n", encoding="utf-8")
    captured = event(tmp_path, "source.md")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(
        "sase.file_hooks.producer.load_file_hooks",
        lambda: [hook("artifact")],
    )
    monkeypatch.setattr(
        "sase.file_hooks.producer.capture_artifact_file_event",
        lambda path: captured,
    )
    stub_detached_spawn(monkeypatch)
    monkeypatch.setattr(
        "sase.artifact_cli.create.store_explicit_artifact_file",
        lambda *args, **kwargs: ArtifactFile(
            id="explicit:test",
            label="source.md",
            kind="markdown",
            path=str(stored),
        ),
    )
    args = argparse.Namespace(
        path=str(source),
        label=None,
        kind=None,
        move=False,
        bead=None,
    )

    assert handle_create(args) == 0
    hook_audits = list_file_hook_audits()
    assert hook_audits
    assert hook_audits[0].outcome == "batch_dispatched"
    assert hook_audits[0].producer == "artifact"
    assert Path(hook_audits[0].events[0]["abs_path"]) == stored
    assert hook_audits[0].batch_path is not None
    payload = json.loads(Path(hook_audits[0].batch_path).read_text(encoding="utf-8"))
    assert payload["runs"][0]["abs_path"] == str(stored)


def test_artifact_create_survives_producer_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# source\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    stored.write_text("# source\n", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(
        "sase.file_hooks.producer.load_file_hooks",
        lambda: (_ for _ in ()).throw(RuntimeError("config exploded")),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.create.store_explicit_artifact_file",
        lambda *args, **kwargs: ArtifactFile(
            id="explicit:test",
            label="source.md",
            kind="markdown",
            path=str(stored),
        ),
    )
    args = argparse.Namespace(
        path=str(source),
        label=None,
        kind=None,
        move=False,
        bead=None,
    )

    assert handle_create(args) == 0
    hook_audits = list_file_hook_audits()
    assert hook_audits[0].outcome == "producer_error"
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications and is_error(notifications[0])
