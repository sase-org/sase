"""End-to-end tests for ``sase memory history`` on a fixture git repo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

sase_core_rs = pytest.importorskip("sase_core_rs")

_REQUIRED_BINDINGS = (
    "memory_history_sync",
    "memory_history_subjects",
    "memory_history_resolve",
    "memory_history_timeline",
    "memory_history_version",
    "memory_history_compare",
    "memory_history_feed",
    "memory_history_wire_schema_version",
)

for _binding in _REQUIRED_BINDINGS:
    if not hasattr(sase_core_rs, _binding):
        pytest.skip(
            f"sase_core_rs is missing binding {_binding!r}",
            allow_module_level=True,
        )

from sase.core import memory_history_facade as facade  # noqa: E402
from sase.core.memory_history_wire import (  # noqa: E402
    MEMORY_HISTORY_WIRE_SCHEMA_VERSION,
)
from sase.memory.history import scopes as history_scopes  # noqa: E402
from sase.memory.history.cli_history import (  # noqa: E402
    handle_memory_history_command,
)
from sase.memory.history.service import HistoryService  # noqa: E402


def _git(repo: Path, *args: str, env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr.decode()[:500]}"
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
def fixture_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    repo = tmp_path / "demo"
    repo.mkdir()
    base_env = {**os.environ}
    _git(repo, "init", "--initial-branch=master", env=base_env)
    _git(repo, "config", "user.name", "SASE Test", env=base_env)
    _git(repo, "config", "user.email", "sase@example.com", env=base_env)
    _git(repo, "config", "commit.gpgsign", "false", env=base_env)
    first = _commit(
        repo,
        "feat(memory): start demo notes",
        "2026-09-20T12:00:00",
        {
            "AGENTS.md": "# Demo\n",
            "sase/memory/note.md": "# Note\n\nOriginal line.\n",
            "sase/memory/legacy_name.md": "# Legacy\n\nOld name.\n",
            "sase/memory/terms.md": "---\nweb: true\n---\n\n# Terms\n",
            "sase/memory/terms/alpha.md": ("---\nkeyword: Alpha\n---\n\nAlpha body.\n"),
            "sase/memory/a/dup.md": "# Dup A\n",
            "sase/memory/b/dup.md": "# Dup B\n",
        },
    )
    _git(
        repo,
        "mv",
        "sase/memory/legacy_name.md",
        "sase/memory/new_name.md",
        env=base_env,
    )
    second = _commit(
        repo,
        "feat(memory): revise note and rename legacy",
        "2026-09-27T12:00:00",
        {"sase/memory/note.md": "# Note\n\nOriginal line.\n\nAdded line.\n"},
    )
    cache_dir = tmp_path / "history-cache"
    monkeypatch.setattr(
        history_scopes, "_default_cache_dir", lambda home=None: cache_dir
    )
    monkeypatch.chdir(repo)
    return {"repo": str(repo), "first": first, "second": second}


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "selectors": [],
        "all": False,
        "at": None,
        "diff": False,
        "format": "text",
        "limit": None,
        "project": None,
        "since": None,
        "scope": "project",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _run(args: argparse.Namespace) -> str:
    console = Console(record=True, width=120, force_terminal=False)
    handle_memory_history_command(args, console=console, service=HistoryService())
    return console.export_text()


def test_wire_schema_version_matches_binding() -> None:
    assert facade.wire_schema_version() == MEMORY_HISTORY_WIRE_SCHEMA_VERSION == 1


def test_timeline_lists_versions_newest_first(
    fixture_repo: dict[str, str],
) -> None:
    text = _run(_args(selectors=["note.md"]))

    assert "note · note · project" in text
    assert "v2" in text and "v1" in text
    assert text.index("v2") < text.index("v1")


def test_at_forms_select_the_same_version(
    fixture_repo: dict[str, str],
) -> None:
    first = fixture_repo["first"]
    expected = _run(_args(selectors=["note.md"], at="v1"))
    assert "Original line." in expected
    for form in ("1", "~2", first[:7], "2026-09-20"):
        text = _run(_args(selectors=["note.md"], at=form))
        assert "Original line." in text, form
        assert "Added line." not in text, form


def test_at_newest_and_now_forms(fixture_repo: dict[str, str]) -> None:
    latest = _run(_args(selectors=["note.md"], at="~1"))
    assert "Added line." in latest
    explicit = _run(_args(selectors=["note.md"], at="v2"))
    assert "Added line." in explicit


def test_diff_shows_word_operations(
    fixture_repo: dict[str, str],
) -> None:
    text = _run(_args(selectors=["note.md"], diff=True))

    assert "{+Added+} {+line.+}" in text


def test_json_timeline_is_the_unchanged_wire(
    fixture_repo: dict[str, str],
) -> None:
    console = Console(record=True, width=120, force_terminal=False)
    handle_memory_history_command(
        _args(selectors=["note.md"], format="json"),
        console=console,
        service=HistoryService(),
    )
    payload = json.loads(console.export_text())

    assert payload["schema_version"] == 1
    assert payload["subject_id"].endswith("/note")
    assert len(payload["versions"]) == 2
    assert payload["versions"][0]["ordinal"] == 2


def test_json_version_includes_body_with_at(
    fixture_repo: dict[str, str],
) -> None:
    console = Console(record=True, width=120, force_terminal=False)
    handle_memory_history_command(
        _args(selectors=["note.md"], at="v1", format="json"),
        console=console,
        service=HistoryService(),
    )
    payload = json.loads(console.export_text())

    assert payload["version"]["ordinal"] == 1
    assert "Original line." in payload["body"]


def test_strand_selector_resolves_through_alias_lookup(
    fixture_repo: dict[str, str],
) -> None:
    text = _run(_args(selectors=["terms:alpha"]))

    assert "alpha" in text
    assert "v1" in text


def test_historical_name_reports_a_notice(
    fixture_repo: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    text = _run(_args(selectors=["legacy_name.md"]))

    assert "is now sase/memory/new_name.md" in text
    _ = capsys


def test_instruction_selectors_produce_no_rename_notice(
    fixture_repo: dict[str, str],
) -> None:
    for selector in ("AGENTS.md", "CLAUDE.md"):
        text = _run(_args(selectors=[selector]))

        assert "is now" not in text


def test_ambiguous_basename_lists_candidates(
    fixture_repo: dict[str, str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(_args(selectors=["dup.md"]))

    assert excinfo.value.code == 1


def test_feed_groups_changesets_by_day(
    fixture_repo: dict[str, str],
) -> None:
    text = _run(_args())

    assert "Memory changes" in text
    assert "Sep 27" in text and "Sep 20" in text
    assert "revise note and rename legacy" in text


def test_history_writes_no_read_audit_rows(
    fixture_repo: dict[str, str], tmp_path: Path
) -> None:
    repo = Path(fixture_repo["repo"])
    _run(_args(selectors=["note.md"]))
    _run(_args(selectors=["note.md"], at="v1"))
    _run(_args(selectors=["note.md"], diff=True))
    _run(_args())

    assert list(repo.glob("**/memory_reads.jsonl")) == []
    assert list(tmp_path.glob("**/memory_reads.jsonl")) == []
