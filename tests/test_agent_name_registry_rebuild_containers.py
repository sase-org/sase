"""Clan, session, and auto-prefix containers for the name registry rebuild.

Split from ``tests.test_agent_name_registry_rebuild``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    get_reserved_agent_names,
    lookup_registered_name,
    rebuild_name_registry,
)

from tests._agent_names_fixtures import make_agent as _make_agent

__all__ = [
    "test_registry_rebuild_agent_session_container_outranks_auto_prefix",
    "test_registry_rebuild_clan_container_outranks_auto_prefix",
    "test_registry_rebuild_collects_active_agent",
    "test_registry_rebuild_collects_agent_session_container",
    "test_registry_rebuild_collects_clan_container",
    "test_registry_rebuild_collects_numeric_auto_prefix",
]


def test_registry_rebuild_collects_active_agent(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()
        assert "foo" in data["entries"]
        assert lookup_registered_name("foo")["state"] == "active"


def test_registry_rebuild_collects_clan_container(tmp_path: Path) -> None:
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo.member")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "foo.member",
                "agent_clan": "foo",
                "agent_clan_generation": "run0",
            }
        ),
        encoding="utf-8",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"foo", "foo.member"} <= set(data["entries"])
    assert data["entries"]["foo"]["container_kind"] == "clan"
    assert data["entries"]["foo"]["clan_generation"] == "run0"


def test_registry_rebuild_collects_agent_session_container(tmp_path: Path) -> None:
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo--0")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "foo--0",
                "workflow_name": "foo",
                "agent_session": "foo",
                "agent_session_role": "root",
                "role_suffix": "--0",
            }
        ),
        encoding="utf-8",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"foo", "foo--0"} <= set(data["entries"])
    assert data["entries"]["foo"]["container_kind"] == "session"
    assert data["entries"]["foo"]["reservation_kind"] == "session"
    assert data["entries"]["foo--0"]["reservation_kind"] == "claimed"


def test_registry_rebuild_agent_session_container_outranks_auto_prefix(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "proj", "run1", "sq.w0")
    _make_agent(
        tmp_path,
        "proj",
        "run2",
        "sq--plan",
        workflow_name="sq",
        agent_session="sq",
        role_suffix="--plan",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["sq"]
    assert entry["container_kind"] == "session"
    assert entry["reservation_kind"] == "session"


def test_registry_rebuild_clan_container_outranks_auto_prefix(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "proj", "run1", "sq.w0")
    clan_dir = _make_agent(tmp_path, "proj", "run2", "sq.member")
    (clan_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "sq.member",
                "model": "test",
                "agent_clan": "sq",
                "agent_clan_generation": "run0",
            }
        ),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["sq"]
    assert entry["container_kind"] == "clan"
    assert entry["reservation_kind"] == "clan"
    assert entry["clan_generation"] == "run0"


def test_registry_rebuild_collects_numeric_auto_prefix(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "1.plan")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        reserved = get_reserved_agent_names()
        assert {"1", "1.plan"} <= reserved
        assert lookup_registered_name("1")["reservation_kind"] == "auto_prefix"
