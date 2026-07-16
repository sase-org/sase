"""Shared helpers for named-agent kill dismissal tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.notifications import (
    Notification,
    append_notification,
    load_notifications,
)


@pytest.fixture(name="isolated_dismissed_index", autouse=True)
def _isolated_dismissed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Redirect named-kill persistence to per-test paths.

    ``sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE`` is bound at import
    time, so tests must override it explicitly to avoid clobbering the real
    ``~/.sase/dismissed_agents.json``.
    """
    from sase.ace import dismissed_agents as mod

    isolated = tmp_path / "dismissed_agents.json"
    monkeypatch.setattr(mod, "_DISMISSED_AGENTS_FILE", isolated)
    from sase.notifications import store

    notifications_dir = tmp_path / "notifications"
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(notifications_dir))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(notifications_dir / "notifications.jsonl"),
    )
    store._invalidate_load_cache()
    yield isolated
    store._invalidate_load_cache()


def setup_home_agent(home: Path, *, with_cl_name: bool = False) -> Path:
    artifacts_dir = (
        home
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260510120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "running.json").write_text(json.dumps({"pid": 11111}))
    meta: dict[str, object] = {"name": "home_agent", "pid": 11111}
    if with_cl_name:
        meta["cl_name"] = "home_feature"
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta))
    return artifacts_dir


def setup_nonhome_agent(home: Path) -> tuple[Path, Path]:
    project_dir = home / ".sase" / "projects" / "myproj"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / "20260510130000"
    artifacts_dir.mkdir(parents=True)
    project_file = project_dir / "myproj.sase"
    project_file.write_text(
        "# Test Project\n\n"
        "RUNNING:\n"
        "  #1 | 22222 | run | feature_x | 20260510130000\n"
        "\n"
        "NAME: feature_x\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "PARENT: None\n"
        "PR: None\n"
        "STATUS: Ready\n"
    )
    return artifacts_dir, project_file


def setup_waiting_agent(
    home: Path,
    *,
    project_name: str,
    timestamp: str,
    name: str,
    pid: int | None,
    cl_name: str,
) -> Path:
    project_dir = home / ".sase" / "projects" / project_name
    artifacts_dir = project_dir / "artifacts" / "ace-run" / timestamp
    artifacts_dir.mkdir(parents=True)
    if project_name != "home":
        (project_dir / f"{project_name}.sase").write_text(
            "# Test Project\n\nNAME: feature_x\nSTATUS: Wip\n",
            encoding="utf-8",
        )
    meta: dict[str, object] = {"name": name, "cl_name": cl_name}
    if pid is not None:
        meta["pid"] = pid
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (artifacts_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["dep_agent"],
                "cl_name": cl_name,
                "timestamp": timestamp,
            }
        ),
        encoding="utf-8",
    )
    return artifacts_dir


def successful_user_kill(status: str = "killed") -> SimpleNamespace:
    return SimpleNamespace(success=True, status=status)


def patch_home(home: Path) -> AbstractContextManager[object]:
    return patch("pathlib.Path.home", return_value=home)


def append_question(
    *,
    notification_id: str,
    cl_name: str,
    child_timestamp: str,
    root_timestamp: str,
    response_dir: Path | None = None,
) -> None:
    action_data = {
        "agent_cl_name": cl_name,
        "agent_timestamp": child_timestamp,
        "agent_root_timestamp": root_timestamp,
    }
    if response_dir is not None:
        action_data["response_dir"] = str(response_dir)
    append_notification(
        Notification(
            id=notification_id,
            timestamp="2026-07-15T10:00:00-04:00",
            sender="question",
            action="UserQuestion",
            action_data=action_data,
        )
    )


def notifications_by_id() -> dict[str, Notification]:
    return {n.id: n for n in load_notifications(include_dismissed=True)}
