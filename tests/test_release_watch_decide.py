"""Binding adapter for the release-steward policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from tests._release_steward_fixtures import releasable_request, unreadable

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "_release_watch_decide.py"
sys.path.insert(0, str(SCRIPT.parent))

import _release_watch_decide as _release_watch_decide  # noqa: E402


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _release_watch_decide


def test_missing_extension_is_watcher_broken(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    monkeypatch.delitem(sys.modules, "sase_core_rs", raising=False)
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sase_core_rs":
            raise ImportError("sase_core_rs is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = tool.decide(releasable_request())
    assert result["primary"]["kind"] == "watcher_broken"
    assert result["primary"]["source"] == "sase_core_rs"
    assert result["process_exit"] == 1
    assert result["train_action"] is None


def test_missing_attribute_is_watcher_broken(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "sase_core_rs", SimpleNamespace())
    result = tool.decide(releasable_request())
    assert result["primary"]["kind"] == "watcher_broken"
    assert "release_steward_decide" in result["details"]
    assert result["process_exit"] == 1


def test_adapter_consumes_registered_binding(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_decide(request: dict[str, Any]) -> dict[str, Any]:
        seen["request"] = request
        return {
            "schema_version": 1,
            "primary": {
                "kind": "releasable",
                "pr_number": 42,
                "head_sha": "a" * 40,
            },
            "details": "ok",
            "evidence": [],
            "blocker_started_at": None,
            "blocker_duration_uncertain": False,
            "train_action": {
                "action": {
                    "kind": "merge_release_pr",
                    "pr_number": 42,
                    "head_sha": "a" * 40,
                },
                "disposition": "proposed",
                "key": "merge:pr=42:head=" + "a" * 40,
                "preconditions": [],
                "argv": ["gh", "pr", "merge", "42"],
                "reason": "merge",
            },
            "escalation": None,
            "secondary": [],
            "process_exit": 0,
        }

    monkeypatch.setitem(
        sys.modules,
        "sase_core_rs",
        SimpleNamespace(release_steward_decide=fake_decide),
    )
    result = tool.decide(releasable_request())
    assert seen["request"]["schema_version"] == 1
    assert result["primary"]["kind"] == "releasable"
    assert result["train_action"]["disposition"] == "proposed"
    assert result["process_exit"] == 0


def test_unreadable_shape_is_distinct_from_absent() -> None:
    missing = unreadable("pypi.sase", "503", "retry PyPI")
    assert missing["status"] == "unreadable"
    assert "value" not in missing
    assert missing["source"] == "pypi.sase"


def test_committed_fact_read_shapes_are_unambiguous() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/release_steward/fact_read_shapes.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(payload) == {"ready", "absent", "unreadable"}
    assert payload["ready"]["status"] == "ready"
    assert "value" in payload["ready"]
    assert payload["absent"]["status"] == "absent"
    assert "value" not in payload["absent"]
    assert payload["unreadable"]["status"] == "unreadable"
    assert "value" not in payload["unreadable"]
    assert payload["unreadable"]["source"]


def test_real_binding_round_trip_when_installed(tool: ModuleType) -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "release_steward_decide"):
        pytest.skip("installed sase_core_rs predates release_steward_decide")
    result = tool.decide(releasable_request())
    assert result["primary"]["kind"] == "releasable"
    assert result["process_exit"] == 0
    assert result["train_action"]["disposition"] != "executed"
