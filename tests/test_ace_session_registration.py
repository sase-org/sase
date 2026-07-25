"""Tests for ACE's live-session registration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.util import session_registration
from sase.ace.tui.util.session_registration import (
    _project_context,
    register_ace_session,
    unregister_ace_session,
)
from sase.workspace_provider.marker import CheckoutMarker


def test_register_ace_session_passes_project_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    def _fake_register(kind: str, **kwargs: Any) -> None:
        recorded["kind"] = kind
        recorded.update(kwargs)

    monkeypatch.setattr(
        session_registration,
        "_project_context",
        lambda _cwd: ("sase", 27),
    )
    monkeypatch.setattr("sase.sessions.register_session", _fake_register)

    register_ace_session("sase ace v1")

    assert recorded["kind"] == "ace"
    assert recorded["project"] == "sase"
    assert recorded["workspace_num"] == 27
    assert recorded["title"] == "sase ace v1"
    assert recorded["cwd"] == os.getcwd()


def test_register_ace_session_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no registry today")

    monkeypatch.setattr("sase.sessions.register_session", _boom)
    register_ace_session("title")  # must not raise


def test_unregister_ace_session_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RuntimeError("gone")

    monkeypatch.setattr("sase.sessions.unregister_session", _boom)
    unregister_ace_session()  # must not raise


def test_project_context_prefers_the_checkout_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = CheckoutMarker(
        project_name="sase",
        project_key="gh_sase-org__sase",
        workspace_num=27,
        primary_workspace_dir="/primary",
        registry_path="/registry.json",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: ("/checkout", marker),
    )
    assert _project_context("/checkout") == ("sase", 27)


def test_project_context_falls_back_to_detection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: None,
    )
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "sase")
    assert _project_context(str(tmp_path)) == ("sase", None)


def test_project_context_when_nothing_resolves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: None,
    )
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: None)
    assert _project_context(str(tmp_path)) == (None, None)
