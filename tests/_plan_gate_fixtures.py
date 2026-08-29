"""Fixtures shared by the plan-gate test modules.

Not a conftest so the fixture only applies to modules that opt in by importing
the re-exported name: ``tests/conftest.py`` ships its own narrower
``gate_home`` that leaves the provider project-dir environment untouched.
"""

from __future__ import annotations

import time
from concurrent.futures import Future
from pathlib import Path
from threading import Event

import pytest

# Approve+commit runs two hashed option commands, each a fresh Python that
# imports sase.plan_gate. The coverage-leg xdist load can spend more than 5s
# on that pair before _archive_plan_for_approval runs, so archive-start waits
# must watch the executor future and budget for subprocess import cost.
ARCHIVE_START_TIMEOUT_SECONDS = 30.0


def wait_for_archive_start(
    started: Event,
    future: Future[object],
    *,
    timeout: float = ARCHIVE_START_TIMEOUT_SECONDS,
) -> None:
    """Wait until the archive mock starts, or fail with the executor error."""
    deadline = time.monotonic() + timeout
    while not started.is_set():
        if future.done():
            exc = future.exception()
            if exc is not None:
                raise AssertionError(
                    "gate selection finished before archive started"
                ) from exc
            raise AssertionError("gate selection finished before archive started")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(
                f"timed out after {timeout}s waiting for archive start"
            )
        started.wait(timeout=min(0.05, remaining))


@pytest.fixture(name="gate_home")
def plan_gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect gate persistence and clear inherited project-dir env vars."""
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda _title, _message: None,
    )
    monkeypatch.setattr("sase.main.plan_approve_handler.get_tmux_prefix", lambda: "")
    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy-pending.json",
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


def write_plan(root: Path, name: str, content: str) -> Path:
    """Write ``content`` to ``root/name`` and return the plan path."""
    path = root / name
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(name="stub_host_plan_archive")
def plan_host_archive_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Publish a host-owned archive path without resolving a real project."""
    saved = tmp_path / "host-archived-plan.md"
    saved.write_text("# archived\n", encoding="utf-8")

    from sase._plan_archive_approval import _ApprovedPlanArchive

    monkeypatch.setattr(
        "sase.plan_approval_actions._archive_plan_for_approval",
        lambda *_args, **_kwargs: _ApprovedPlanArchive(
            saved,
            "plan:202608/host-archived-plan.md",
        ),
    )
    return saved
