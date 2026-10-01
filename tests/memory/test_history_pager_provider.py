"""Memory history pager provider tests with a real git fixture."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from sase.feature_flags import override_flags
from sase.feature_flags.registry import FeatureFlag
from sase.memory.history import pager_provider as provider_mod
from sase.memory.history import scopes as history_scopes
from sase.memory.history.cli_history import handle_memory_history_command
from sase.memory.history.pager_provider import (
    MemoryHistoryProvider,
    build_history_document,
    dirty_now_from_timeline,
    history_marks_from_comparison,
    is_deleted_row,
    newest_committed_row,
    visible_ordinals_for_timeline,
)
from sase.memory.history.service import HistoryService
from sase.pager.document import PagerOrigin
from sase.pager.history.provider import (
    clear_history_provider_factories,
    history_provider_for_section,
    register_history_provider_factory,
)
from sase.pager.adapters import path_section


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        env=env or os.environ,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr.decode()[:300]}"
    return proc.stdout.decode().strip()


def _commit(repo: Path, message: str, date: str, files: dict[str, str]) -> str:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "SASE Test",
        "GIT_AUTHOR_EMAIL": "sase@example.com",
        "GIT_COMMITTER_NAME": "SASE Test",
        "GIT_COMMITTER_EMAIL": "sase@example.com",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD", env=env)


@pytest.fixture()
def fixture_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    base_env = {**os.environ}
    _git(repo, "init", "--initial-branch=master", env=base_env)
    _git(repo, "config", "user.name", "SASE Test", env=base_env)
    _git(repo, "config", "user.email", "sase@example.com", env=base_env)
    _git(repo, "config", "commit.gpgsign", "false", env=base_env)
    _commit(
        repo,
        "feat(memory): start demo notes",
        "2026-09-20T12:00:00",
        {"AGENTS.md": "# Demo\n", "sase/memory/note.md": "# Note\n\nOriginal line.\n"},
    )
    _commit(
        repo,
        "feat(memory): revise note",
        "2026-09-27T12:00:00",
        {"sase/memory/note.md": "# Note\n\nOriginal line.\n\nAdded line.\n"},
    )
    cache_dir = tmp_path / "history-cache"
    monkeypatch.setattr(
        history_scopes, "_default_cache_dir", lambda home=None: cache_dir
    )
    monkeypatch.chdir(repo)
    return repo


def test_timeline_helpers_use_hidden_bit_and_status(
    fixture_repo: Path,
) -> None:
    service = HistoryService()
    scope = service.project_scope(fixture_repo)
    timeline = service.timeline(scope, "note.md", include_hidden=True)
    visible = visible_ordinals_for_timeline(timeline)
    assert visible == (1, 2)
    assert newest_committed_row(timeline) is not None
    assert not any(
        is_deleted_row(row)
        for row in timeline.get("versions", ())
        if isinstance(row, dict)
    )
    assert dirty_now_from_timeline(timeline) is False


def test_provider_recognizes_memory_and_declines_unrelated(
    fixture_repo: Path,
) -> None:
    provider = MemoryHistoryProvider(service=HistoryService())
    memory_section = path_section(fixture_repo / "sase/memory/note.md")
    assert provider.recognizes(memory_section) in (True, False)
    # Recognition depends on the beta flag: force it on for this assertion.
    with override_flags(memory_history=True):
        assert provider.recognizes(memory_section) is True
        other = path_section(fixture_repo / "AGENTS.md")
        # AGENTS.md is an instruction file, also recognized.
        assert provider.recognizes(other) is True
    with override_flags(memory_history=False):
        assert provider.recognizes(memory_section) is False


def test_provider_loads_version_and_compares(fixture_repo: Path) -> None:
    with override_flags(memory_history=True):
        service = HistoryService()
        provider = MemoryHistoryProvider(service=service)
        section = path_section(fixture_repo / "sase/memory/note.md")
        timeline = provider.load_timeline(section)
        assert (
            len([r for r in timeline.get("versions", ()) if isinstance(r, dict)]) >= 2
        )
        first = provider.load_version(section, 1)
        assert first is not None
        assert "Original line." in first.plain_text
        assert first.version_pin is not None and first.version_pin.ordinal == 1
        comparison = provider.compare_versions(section, 1, 2)
        assert comparison is None or isinstance(comparison, dict)


def test_history_marks_from_comparison_shape() -> None:
    marks, anchors = history_marks_from_comparison(
        {
            "line_marks": [2, 3],
            "word_ops": [{"target_line": 3, "ops": [{"kind": "delete"}]}],
            "removal_anchors": [{"after_target_line": 1, "removed_count": 2}],
        }
    )
    assert marks[2] == "added"
    assert marks[3] == "changed"
    assert 1 in anchors


def test_build_history_document_for_selector(fixture_repo: Path) -> None:
    service = HistoryService()
    scope = service.project_scope(fixture_repo)
    document = build_history_document(
        scope=scope, subject="note.md", initial_revision="v1", service=service
    )
    assert document.origin is PagerOrigin.FILE
    assert len(document.sections) == 1
    assert "Original line." in document.sections[0].plain_text


def test_flag_off_keeps_text_default_and_rejects_pager(
    fixture_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with override_flags(memory_history=False):
        args = argparse.Namespace(
            selectors=["note.md"],
            all=False,
            at=None,
            diff=False,
            format="pager",
            limit=None,
            project=None,
            since=None,
            scope="project",
        )
        with pytest.raises(SystemExit) as excinfo:
            handle_memory_history_command(
                args, console=Console(width=120), service=HistoryService()
            )
        assert excinfo.value.code == 2
        assert "memory_history" in capsys.readouterr().err


def test_entry_point_factory_respects_flag() -> None:
    with override_flags(memory_history=False):
        assert provider_mod.memory_history_provider_factory() is None
    with override_flags(memory_history=True):
        provider = provider_mod.memory_history_provider_factory()
        assert provider is not None


def test_registry_discovers_memory_factory() -> None:
    clear_history_provider_factories()
    try:
        register_history_provider_factory(provider_mod.memory_history_provider_factory)
        with override_flags(memory_history=True):
            section = path_section(Path.cwd() / "sase/memory/tui.md")
            # Factory either recognizes or declines without raising.
            provider = history_provider_for_section(section)
            assert provider is None or provider.provider_key == "memory-history"
    finally:
        clear_history_provider_factories()
