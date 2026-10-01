"""Memory history pager provider tests with a real git fixture."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from sase.memory.history import pager_provider as provider_mod
from sase.memory.history import scopes as history_scopes
from sase.memory.history.cli_history import handle_memory_history_command
from sase.memory.history.pager_provider import (
    build_history_document,
    dirty_now_from_timeline,
    history_marks_from_comparison,
    is_deleted_row,
    newest_committed_row,
    visible_ordinals_for_timeline,
)
from sase.memory.history.pager_provider_core import (
    _MemoryHistoryProvider,
    _tombstone_banner,
)
from sase.memory.history.render_text import format_banner_date
from sase.memory.history.service import HistoryService
from sase.pager.document import PagerOrigin
from sase.pager.history.provider import (
    clear_history_provider_factories,
    history_factories_snapshot,
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
    provider = _MemoryHistoryProvider(service=HistoryService())
    memory_section = path_section(fixture_repo / "sase/memory/note.md")
    assert provider.recognizes(memory_section) is True
    other = path_section(fixture_repo / "AGENTS.md")
    # AGENTS.md is an instruction file, also recognized.
    assert provider.recognizes(other) is True
    plain = fixture_repo / "unrelated.txt"
    plain.write_text("nothing to do with memory\n", encoding="utf-8")
    assert provider.recognizes(path_section(plain)) is False


def test_provider_loads_version_and_compares(fixture_repo: Path) -> None:
    service = HistoryService()
    provider = _MemoryHistoryProvider(service=service)
    section = path_section(fixture_repo / "sase/memory/note.md")
    timeline = provider.load_timeline(section)
    assert len([r for r in timeline.get("versions", ()) if isinstance(r, dict)]) >= 2
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


def test_tombstone_banner_uses_date_actor_and_separator() -> None:
    epoch = 1787677072
    banner = _tombstone_banner(
        {
            "class": "deleted",
            "committer_time": epoch,
            "author_time": epoch - 60,
            "author_name": "SASE Test",
            "provenance": {"agent": "athena.test", "bead": "sase-1"},
        }
    )

    assert "✖ deleted " in banner
    assert str(epoch) not in banner
    assert " · last content shown" in banner
    assert "by athena.test" in banner
    assert (
        _tombstone_banner(
            {
                "class": "deleted",
                "committer_time": epoch,
                "provenance": {"agent": "athena.test"},
            }
        )
        .split(" by ")[0]
        .endswith(format_banner_date(epoch))
    )


def test_tombstone_banner_falls_back_to_author_name_then_unknown() -> None:
    epoch = 1787677072
    by_author = _tombstone_banner(
        {
            "class": "deleted",
            "author_time": epoch,
            "author_name": "SASE Test",
            "provenance": {},
        }
    )

    assert "by SASE Test" in by_author
    assert str(epoch) not in by_author
    unknown = _tombstone_banner({"class": "deleted"})

    assert "by unknown" in unknown


class _CannedVersionService:
    """HistoryService stub returning one canned version response."""

    def __init__(self, response: dict[str, object], repo_root: Path) -> None:
        self._response = response
        self._repo_root = repo_root

    def project_scope(self, checkout: object) -> argparse.Namespace:
        return argparse.Namespace(repo_root=str(self._repo_root))

    def version(
        self,
        scope: object,
        selector: str,
        revision: str,
        *,
        include_body: bool = False,
    ) -> dict[str, object]:
        return dict(self._response)


def test_load_version_uses_version_path_for_title_and_links(
    fixture_repo: Path,
) -> None:
    response: dict[str, object] = {
        "existed": True,
        "body": "# Note\n",
        "version": {
            "ordinal": 2,
            "class": "moved",
            "path": "memory/build_and_run.md",
            "commit": "0" * 40,
        },
    }
    provider = _MemoryHistoryProvider(
        service=_CannedVersionService(response, fixture_repo),  # type: ignore[arg-type]
    )
    section = path_section(fixture_repo / "sase/memory/note.md")

    derived = provider.load_version(section, 2)

    assert derived is not None
    assert derived.title == "build_and_run.md"
    assert derived.owner is not None
    assert derived.owner.source_directory == str(fixture_repo / "memory")
    pin = derived.version_pin
    assert pin is not None and pin.ordinal == 2


def test_load_version_renders_tombstone_banner(fixture_repo: Path) -> None:
    epoch = 1787677072
    response: dict[str, object] = {
        "existed": True,
        "body": "# Gone\n",
        "version": {
            "ordinal": 3,
            "class": "deleted",
            "path": "sase/memory/gone.md",
            "commit": "1" * 40,
            "committer_time": epoch,
            "author_time": epoch,
            "author_name": "SASE Test",
            "provenance": {"agent": "athena.test"},
        },
    }
    provider = _MemoryHistoryProvider(
        service=_CannedVersionService(response, fixture_repo),  # type: ignore[arg-type]
    )
    section = path_section(fixture_repo / "sase/memory/note.md")

    derived = provider.load_version(section, 3)

    assert derived is not None
    banner_line = derived.plain_text.splitlines()[0]
    assert str(epoch) not in banner_line
    assert " · last content shown" in banner_line
    assert "by athena.test" in banner_line


def test_entry_point_factory_builds_provider() -> None:
    provider = provider_mod.memory_history_provider_factory()
    assert provider is not None
    assert provider.provider_key == "memory-history"


def test_registry_discovers_memory_factory() -> None:
    clear_history_provider_factories()
    try:
        register_history_provider_factory(provider_mod.memory_history_provider_factory)
        section = path_section(Path.cwd() / "sase/memory/tui.md")
        # Factory either recognizes or declines without raising.
        provider = history_provider_for_section(section)
        assert provider is None or provider.provider_key == "memory-history"
    finally:
        clear_history_provider_factories()


def test_build_history_document_honors_diff_view(fixture_repo: Path) -> None:
    service = HistoryService()
    scope = service.project_scope(fixture_repo)
    read = build_history_document(scope=scope, subject="note.md", service=service)
    read_pin = read.sections[0].version_pin
    assert read_pin is not None
    assert getattr(read_pin, "view", "read") == "read"
    diff = build_history_document(
        scope=scope, subject="note.md", view="diff", service=service
    )
    diff_pin = diff.sections[0].version_pin
    assert diff_pin is not None and diff_pin.view == "diff"
    based = build_history_document(
        scope=scope,
        subject="note.md",
        initial_revision="v2",
        view="diff",
        compare_base="v1",
        service=service,
    )
    based_pin = based.sections[0].version_pin
    assert based_pin is not None
    assert based_pin.ordinal == 2
    assert based_pin.view == "diff"
    assert based_pin.compare_base == 1


def test_diff_view_renders_real_core_comparison(fixture_repo: Path) -> None:
    from sase.pager.history.diff import build_diff_body

    service = HistoryService()
    provider = _MemoryHistoryProvider(service=service)
    section = path_section(fixture_repo / "sase/memory/note.md")
    comparison = provider.compare_versions(section, 1, 2)
    assert isinstance(comparison, dict)
    assert "unified_diff" in comparison
    target = provider.load_version(section, 2)
    assert target is not None
    rendered = build_diff_body(comparison, target.plain_text)
    assert "Added line." in rendered.text.plain
    assert rendered.change_lines


def test_bare_note_selector_attaches_history(fixture_repo: Path) -> None:
    service = HistoryService()
    scope = service.project_scope(fixture_repo)
    provider = _MemoryHistoryProvider(service=service)
    document = build_history_document(scope=scope, subject="note.md", service=service)
    section = document.sections[0]
    # The resolved repo-relative path is stamped, so the bare selector
    # attaches even though it never names the memory root.
    assert section.subject_ref == "sase/memory/note.md"
    assert provider.recognizes(section) is True
    pin = section.version_pin
    assert pin is not None and str(pin.subject_id).startswith("note:")


def test_memory_subject_pin_recognized_without_path_text() -> None:
    from sase.pager.document import PagerSection
    from sase.pager.history.models import committed_pin_for_ordinal

    provider = _MemoryHistoryProvider(service=None)
    for subject_id in (
        "note:project:demo/decisions",
        "web:project:demo/decisions",
        "strand:project:demo/glossary/stitch",
        "instructions:project:demo",
    ):
        section = PagerSection(
            identity="history:decisions:now",
            title="decisions",
            kind="file",
            body="body\n",
            subject_ref="decisions",
            version_pin=committed_pin_for_ordinal(subject_id, 1),
        )
        assert provider.recognizes(section) is True, subject_id
    other = PagerSection(
        identity="other",
        title="other",
        kind="file",
        body="body\n",
        subject_ref="other.txt",
        version_pin=committed_pin_for_ordinal("file:other.txt", 1),
    )
    assert provider.recognizes(other) is False


def test_builtin_factory_found_when_entry_points_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *a, **k: [])
    clear_history_provider_factories()
    try:
        factories = history_factories_snapshot()
        providers = [factory() for factory in factories]
        assert any(
            getattr(provider, "provider_key", None) == "memory-history"
            for provider in providers
        )
    finally:
        clear_history_provider_factories()


def test_dirty_detection_from_pseudo_rows() -> None:
    assert (
        dirty_now_from_timeline(
            {
                "versions": [
                    {"ordinal": 0, "class": "uncommitted"},
                    {"ordinal": 1, "class": "authored"},
                ]
            }
        )
        is True
    )
    assert (
        dirty_now_from_timeline({"versions": [{"ordinal": 0, "class": "staged"}]})
        is True
    )
    assert (
        dirty_now_from_timeline({"versions": [{"ordinal": 1, "class": "authored"}]})
        is False
    )


def test_cli_diff_flag_opens_diff_view(
    fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.pager.app as pager_app

    captured: dict[str, object] = {}

    class _FakePager:
        def __init__(self, document: object) -> None:
            captured["document"] = document

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(pager_app, "SasePager", _FakePager)
    args = argparse.Namespace(
        selectors=["note.md"],
        all=False,
        at=None,
        diff=True,
        format="pager",
        limit=None,
        project=None,
        since=None,
        scope="project",
    )
    handle_memory_history_command(
        args, console=Console(width=120), service=HistoryService()
    )
    assert captured.get("ran") is True
    document = captured["document"]
    assert document is not None and len(document.sections) == 1  # type: ignore[union-attr]
    pin = document.sections[0].version_pin  # type: ignore[union-attr]
    assert pin is not None and pin.view == "diff"
