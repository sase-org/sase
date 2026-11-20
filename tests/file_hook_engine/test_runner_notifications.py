"""Notification quieting for detached file-hook runs.

A hook's successes share one silent row refreshed in place; a failure stays
visible and repeats of one failure +1 a single row.
"""

from __future__ import annotations

from pathlib import Path
import shlex
import sys
from unittest.mock import MagicMock

from sase.config.file_hooks import FileHookConfig
from sase.file_hooks.engine import emit_file_hook_events
from sase.file_hooks.runner import execute_batch
from sase.notifications.models import Notification
from sase.notifications.priority import is_error
from sase.notifications.store import load_notifications, mark_dismissed

from .helpers import event, hook, init_repo

_PYTHON = shlex.quote(sys.executable)


def _run_hook(repo: Path, hook_config: FileHookConfig, path: str) -> None:
    (repo / path).write_text(f"# {path}\n", encoding="utf-8")
    batch_path = emit_file_hook_events(
        [event(repo, path)],
        hooks=[hook_config],
        popen=lambda *args, **kwargs: MagicMock(),
    )
    assert batch_path is not None
    assert execute_batch(batch_path) == 0


def _file_hook_rows(*, include_dismissed: bool = False) -> list[Notification]:
    return [
        row
        for row in load_notifications(include_dismissed=include_dismissed)
        if row.sender == "file-hooks"
    ]


def _failing_hook(name: str = "lint") -> FileHookConfig:
    code = shlex.quote("raise SystemExit(3)")
    return hook(name, f"{_PYTHON} -c {code}")


def test_successes_share_one_silent_row_refreshed_in_place(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    ok = hook("fmt", "true")

    for path in ("a.md", "b.md", "c.md"):
        _run_hook(repo, ok, path)

    rows = _file_hook_rows(include_dismissed=True)
    assert len(rows) == 1
    row = rows[0]
    assert row.silent is True
    assert not is_error(row)
    assert row.action is None
    assert row.plus_ones == []
    assert row.dedup_key is not None
    assert row.dedup_key.startswith("file-hooks:ok:")
    # The single row shows the latest run and links that run's log.
    assert row.notes[0] == "✅ fmt: c.md"
    assert row.notes[-1].startswith("last success: ")
    assert len(row.files) == 1
    log_command = Path(row.files[0]).read_text(encoding="utf-8").splitlines()[0]
    assert log_command == f"command: true {repo / 'c.md'}"


def test_each_hook_keeps_its_own_success_row(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    _run_hook(repo, hook("fmt", "true"), "a.md")
    _run_hook(repo, hook("index", "true"), "a.md")
    _run_hook(repo, hook("fmt", "true"), "b.md")

    rows = _file_hook_rows()
    assert sorted(row.notes[0] for row in rows) == ["✅ fmt: b.md", "✅ index: a.md"]
    assert all(row.silent for row in rows)


def test_failure_stays_visible_and_repeats_plus_one_one_row(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    failing = _failing_hook()

    _run_hook(repo, failing, "a.md")
    _run_hook(repo, failing, "b.md")
    _run_hook(repo, failing, "b.md")

    rows = _file_hook_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.silent is False
    assert is_error(row)
    assert row.action == "ViewErrorReport"
    assert row.notes[0] == "❌ lint failed: a.md"
    assert row.dedup_key is not None
    assert row.dedup_key.startswith("file-hooks:failed:")
    # The identical third failure coalesces through the store guard.
    assert [plus_one.note for plus_one in row.plus_ones] == ["❌ b.md: exit 3"]


def test_failure_signatures_and_successes_stay_apart(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    exit_four = shlex.quote("raise SystemExit(4)")

    _run_hook(repo, _failing_hook(), "a.md")
    _run_hook(repo, hook("lint", f"{_PYTHON} -c {exit_four}"), "a.md")
    _run_hook(repo, hook("lint", "true"), "a.md")

    rows = _file_hook_rows()
    failures = sorted(row.notes[-1] for row in rows if not row.silent)
    assert failures == ["exit code: 3", "exit code: 4"]
    assert [row.notes[0] for row in rows if row.silent] == ["✅ lint: a.md"]


def test_failure_after_dismissal_opens_a_fresh_visible_row(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    failing = _failing_hook()

    _run_hook(repo, failing, "a.md")
    first = _file_hook_rows()[0]
    assert mark_dismissed(first.id)
    _run_hook(repo, failing, "b.md")

    live = _file_hook_rows()
    assert len(live) == 1
    assert live[0].id != first.id
    assert live[0].notes[0] == "❌ lint failed: b.md"
    assert live[0].dedup_key == first.dedup_key


def test_dismissed_success_row_stays_dismissed_but_refreshes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    ok = hook("fmt", "true")

    _run_hook(repo, ok, "a.md")
    row = _file_hook_rows()[0]
    assert mark_dismissed(row.id)
    _run_hook(repo, ok, "b.md")

    assert _file_hook_rows() == []
    rows = _file_hook_rows(include_dismissed=True)
    assert len(rows) == 1
    assert rows[0].id == row.id
    assert rows[0].dismissed is True
    assert rows[0].notes[0] == "✅ fmt: b.md"
