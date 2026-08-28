"""Settle-time next-action hook resolution, keyed by gate kind."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.gate_shell.kind_next_action import resolve_shell_next_action


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "question",
        "artifacts_dir": "/tmp/does-not-matter",
        "meta": {},
        "envelope": {},
        "response": {},
        "declared": "declared prompt",
    }
    base.update(overrides)
    return base


def test_unregistered_kind_returns_declared() -> None:
    assert resolve_shell_next_action(**_kwargs(kind="custom")) == "declared prompt"


def test_none_kind_returns_declared() -> None:
    assert resolve_shell_next_action(**_kwargs(kind=None)) == "declared prompt"


def test_registered_hook_return_value_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.gate_shell.kind_next_action as module

    monkeypatch.setitem(
        module._KIND_NEXT_ACTIONS,
        "question",
        _rebuild_ok,
    )
    assert resolve_shell_next_action(**_kwargs()) == "rebuilt next action"


def test_import_failure_falls_back_to_declared(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import sase.gate_shell.kind_next_action as module

    monkeypatch.setitem(module._KIND_NEXT_ACTIONS, "question", _rebuild_unimportable)
    with caplog.at_level(logging.WARNING):
        result = resolve_shell_next_action(**_kwargs())
    assert result == "declared prompt"
    assert "next-action hook failed" in caplog.text


def test_raising_hook_falls_back_to_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.gate_shell.kind_next_action as module

    monkeypatch.setitem(
        module._KIND_NEXT_ACTIONS,
        "question",
        _rebuild_raises,
    )
    assert resolve_shell_next_action(**_kwargs()) == "declared prompt"


def test_falsy_return_falls_back_to_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.gate_shell.kind_next_action as module

    monkeypatch.setitem(
        module._KIND_NEXT_ACTIONS,
        "question",
        _rebuild_empty,
    )
    assert resolve_shell_next_action(**_kwargs()) == "declared prompt"


def _rebuild_ok(**kwargs: Any) -> str:
    del kwargs
    return "rebuilt next action"


def _rebuild_raises(**kwargs: Any) -> str:
    del kwargs
    raise RuntimeError("boom")


def _rebuild_unimportable(**kwargs: Any) -> str:
    """Stand in for a hook whose own module import fails at settlement."""
    del kwargs
    from sase.question_shell.does_not_exist import missing_hook  # noqa: F401

    return "unreachable"


def _rebuild_empty(**kwargs: Any) -> str:
    del kwargs
    return ""
