"""Fixtures shared by the plan-gate test modules.

Not a conftest so the fixture only applies to modules that opt in by importing
the re-exported name: ``tests/conftest.py`` ships its own narrower
``gate_home`` that leaves the provider project-dir environment untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(name="gate_home")
def plan_gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect gate persistence and clear inherited project-dir env vars."""
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda _title, _message: None,
    )
    monkeypatch.setattr("sase.main.plan_approve_handler.ring_tmux_bell", lambda: None)
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
    monkeypatch.setattr(
        "sase.plan_approval_actions._archive_plan_for_approval",
        lambda *_args, **_kwargs: str(saved),
    )
    return saved
