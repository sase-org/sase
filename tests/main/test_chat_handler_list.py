"""Tests for the ``sase chat list`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.chat.cli_list import handle_chat_list
from sase.history.chat_catalog import chat_info_to_json
from sase.history.chat_catalog_provenance import (
    CHAT_PROVENANCE_VALUES,
    chat_provenance_badge,
)

from tests.main.chat_handler_helpers import (
    catalog_entry,
    fake_catalog,
    setup_fake_home,
    write_chat,
)


def _list_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "json": False,
        "limit": 20,
        "machine": None,
        "provenance": None,
        "query": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_list_json_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_fake_home(monkeypatch, tmp_path)
    handle_chat_list(_list_args(json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_list_json_shape_and_key_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = setup_fake_home(monkeypatch, tmp_path)
    write_chat(
        home,
        "branch-run-planner-260429_101500",
        workflow="run",
        agent="planner",
        prompt="Can you help",
        response="Implemented",
    )
    handle_chat_list(_list_args(json=True))
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 1
    row = data[0]
    assert list(row.keys()) == [
        "path",
        "basename",
        "mtime",
        "size_bytes",
        "workflow",
        "agent",
        "timestamp",
        "prompt_snippet",
        "response_snippet",
        "provenance",
        "source_machine",
        "source_username",
        "project_key",
        "agent_artifact_dir",
        "agent_local_name",
        "agent_global_name",
        "sidecar_repo",
        "sidecar_relpath",
        "publication_pending",
        "publication_last_error",
        "publication_quarantined",
        "publication_attempts",
        "publication_disposition",
    ]
    assert row["provenance"] in CHAT_PROVENANCE_VALUES
    assert row["basename"] == "branch-run-planner-260429_101500"
    assert row["workflow"] == "run"
    assert row["agent"] == "planner"
    assert row["prompt_snippet"] == "Can you help"
    assert row["response_snippet"] == "Implemented"
    assert row["publication_attempts"] is None
    assert row["publication_disposition"] is None


def test_catalog_json_appends_attempts_and_mixed_disposition() -> None:
    row = chat_info_to_json(
        catalog_entry(
            publication_pending=True,
            publication_quarantined=False,
            publication_attempts=8,
            publication_disposition="mixed",
        )
    )

    assert list(row)[-2:] == [
        "publication_attempts",
        "publication_disposition",
    ]
    assert row["publication_attempts"] == 8
    assert row["publication_disposition"] == "mixed"


def test_list_projects_only_local_machine_hood(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    entries = [
        catalog_entry(agent="athena.alpha"),
        catalog_entry(agent="zeus.beta", basename="foreign"),
    ]

    with patch("sase.chat.cli_list.load_chat_catalog", fake_catalog(entries)):
        handle_chat_list(_list_args(json=True))

    rows = json.loads(capsys.readouterr().out)
    assert [row["agent"] for row in rows] == ["alpha", "zeus.beta"]


def test_list_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = setup_fake_home(monkeypatch, tmp_path)
    for i in range(5):
        write_chat(home, f"branch-run-26042{i}_101500")
    handle_chat_list(_list_args(json=True, limit=2))
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2


def test_list_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = setup_fake_home(monkeypatch, tmp_path)
    write_chat(home, "alpha-run-260429_101500", prompt="brown fox")
    write_chat(home, "beta-run-260429_101501", prompt="something else")
    handle_chat_list(_list_args(json=True, query="brown"))
    data = json.loads(capsys.readouterr().out)
    assert [r["basename"] for r in data] == ["alpha-run-260429_101500"]


def test_list_pretty_table_renders(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pretty table delegates to load_chat_catalog and renders rows."""
    monkeypatch.setenv("COLUMNS", "200")
    entries = [
        catalog_entry(basename="alpha-run-260429_101500", agent="alpha"),
        catalog_entry(basename="beta-run-260429_101501", agent="beta"),
    ]
    with patch("sase.chat.cli_list.load_chat_catalog", fake_catalog(entries)):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (2)" in out
    assert "alpha-run-260429_101500" in out
    assert "beta-run-260429_101501" in out
    # The table trims the ISO mtime to minute precision; JSON keeps it whole.
    assert "2026-04-29 10:15" in out
    assert "10:15:08-04:00" not in out


def test_list_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sase.chat.cli_list.load_chat_catalog", fake_catalog([])):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (0)" in out
    assert "No chat transcripts found" in out


def test_list_pretty_renders_every_provenance_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every provenance state renders its own badge without raising."""
    monkeypatch.setenv("COLUMNS", "200")
    entries = [
        catalog_entry(
            basename=f"{provenance}-run-260429_10150{index}",
            provenance=provenance,
            source_machine="zeus" if provenance == "remote" else "athena",
        )
        for index, provenance in enumerate(CHAT_PROVENANCE_VALUES)
    ]
    with patch("sase.chat.cli_list.load_chat_catalog", fake_catalog(entries)):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "SYNC" in out
    assert "MACHINE" in out
    for provenance in CHAT_PROVENANCE_VALUES:
        badge = chat_provenance_badge(provenance)
        assert badge.glyph in out
        if provenance != "unknown":
            assert badge.label in out
    assert "↓" in out
    assert "○" in out
    assert "⇣" not in out
    assert "◌" not in out
    assert "zeus" in out


def test_list_forwards_provenance_and_machine_filters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = [
        catalog_entry(
            basename="local-chat", provenance="local", source_machine="athena"
        ),
        catalog_entry(
            basename="remote-chat", provenance="remote", source_machine="zeus"
        ),
        catalog_entry(
            basename="other-remote", provenance="remote", source_machine="hermes"
        ),
    ]
    loader = fake_catalog(entries)
    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, provenance="remote"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["remote-chat", "other-remote"]
    assert loader.calls[-1]["provenance"] == "remote"

    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, machine="ZEUS"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["remote-chat"]
    assert loader.calls[-1]["machine"] == "ZEUS"


def test_list_ignores_unrecognized_provenance_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bogus provenance value degrades to "no filter" instead of raising."""
    entries = [catalog_entry(basename="local-chat", provenance="local")]
    loader = fake_catalog(entries)
    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, provenance="bogus"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["local-chat"]
    assert loader.calls[-1]["provenance"] is None
