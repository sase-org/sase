"""Artifact deletion respects active prompt-archive publication requests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_outbox_store import mutate_publication_outbox


def _publication_row(
    artifacts_dir: Path,
    *,
    terminal: bool = False,
    quarantined: bool = False,
    last_error: str | None = None,
) -> AgentPublicationOutboxItem:
    name = artifacts_dir.name
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=name,
        global_agent=f"alice.athena.{name}",
        primary_revision=(name.encode("utf-8").hex() * 40)[:40],
        local_hood=name,
        artifacts_dir=str(artifacts_dir),
        terminal=terminal,
        quarantined=quarantined,
        last_error=last_error,
    )


def _set_publication_rows(*rows: AgentPublicationOutboxItem) -> None:
    mutate_publication_outbox("proj", lambda _current: rows)


def test_active_publication_row_defers_artifact_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt = artifacts_dir / "raw_prompt.md"
    prompt.write_text("Keep this prompt.\n", encoding="utf-8")
    _set_publication_rows(_publication_row(artifacts_dir))

    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts"
        ) as mock_delete,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
    ):
        assert delete_agent_artifacts(str(artifacts_dir)) is False

    assert prompt.read_text(encoding="utf-8") == "Keep this prompt.\n"
    mock_delete.assert_not_called()
    mock_delete_index.assert_not_called()


def test_terminal_quarantined_and_unreferenced_dirs_can_be_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    terminal_dir = tmp_path / "terminal"
    quarantined_dir = tmp_path / "quarantined"
    unreferenced_dir = tmp_path / "unreferenced"
    for directory in (terminal_dir, quarantined_dir, unreferenced_dir):
        directory.mkdir()
    _set_publication_rows(
        _publication_row(terminal_dir, terminal=True),
        _publication_row(quarantined_dir, quarantined=True),
    )

    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    def delete_directory(path: str | None) -> bool:
        assert path is not None
        shutil.rmtree(path)
        return True

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            side_effect=delete_directory,
        ),
        patch(
            "sase.ace.tui.actions.agents._killing_utils.delete_agent_artifact_index_artifacts"
        ),
    ):
        for directory in (terminal_dir, quarantined_dir, unreferenced_dir):
            assert delete_agent_artifacts(str(directory)) is True
            assert not directory.exists()


def test_monitor_publication_row_pins_starter_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monitor_dir = tmp_path / "monitor"
    starter_dir = tmp_path / "starter"
    monitor_dir.mkdir()
    starter_dir.mkdir()
    (monitor_dir / "agent_meta.json").write_text(
        json.dumps({"monitor_starter_artifacts_dir": str(starter_dir)}),
        encoding="utf-8",
    )
    _set_publication_rows(_publication_row(monitor_dir))

    from sase.agents_sync.prompt_archive.source import _active_prompt_source_pins

    pins = _active_prompt_source_pins()

    assert pins is not None
    assert str(starter_dir.resolve()) in pins


def test_unreadable_outbox_defers_artifact_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    outbox = tmp_path / ".sase/projects/proj/agents-publication-outbox.json"
    outbox.parent.mkdir(parents=True)
    outbox.write_text("{broken", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt = artifacts_dir / "raw_prompt.md"
    prompt.write_text("Retain on read failure.\n", encoding="utf-8")

    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    with patch(
        "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts"
    ) as mock_delete:
        assert delete_agent_artifacts(str(artifacts_dir)) is False

    mock_delete.assert_not_called()
    assert prompt.is_file()


def test_prompt_pin_memo_invalidates_when_outbox_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    active = _publication_row(artifacts_dir)
    _set_publication_rows(active)

    from sase.agents_sync.prompt_archive.source import _active_prompt_source_pins

    first = _active_prompt_source_pins()
    assert first is not None
    assert str(artifacts_dir.resolve()) in first

    _set_publication_rows(
        _publication_row(artifacts_dir, terminal=True, last_error="x" * 80)
    )
    second = _active_prompt_source_pins()

    assert second == frozenset()
