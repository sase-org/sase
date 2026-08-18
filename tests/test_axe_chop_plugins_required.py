"""Five-minute plugins_required chop reconciliation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_plugins_required as plugins_required

from tests._axe_chop_plugins_required_helpers import (
    capture_canceled,
    capture_created,
    expected_counters,
    make_runtime,
    missing_entry,
    patch_projects,
)


def _state(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / plugins_required._STATE_FILENAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_dry_run_creates_no_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(monkeypatch, tmp_path, [missing_entry()])
    created = capture_created(monkeypatch)

    result = plugins_required._run(make_runtime(tmp_path, dry_run=True))

    assert result.reason == "dry_run"
    assert created == []
    assert _state(tmp_path) == {}


def test_satisfied_project_creates_no_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(monkeypatch, tmp_path, [])
    created = capture_created(monkeypatch)

    result = plugins_required._run(make_runtime(tmp_path))

    assert result.reason == "no_required_plugin_changes"
    assert result.counters == expected_counters()
    assert created == []
    assert _state(tmp_path) == {}


def test_missing_set_creates_one_gate_per_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = [missing_entry()]
    patch_projects(
        monkeypatch,
        tmp_path,
        {
            "sase": missing,
            "other": [
                missing_entry(
                    requirement="sase-research-artifacts",
                    name="sase-research-artifacts",
                    install_command="sase plugin install sase-research-artifacts",
                )
            ],
        },
    )
    created = capture_created(monkeypatch)

    result = plugins_required._run(make_runtime(tmp_path))

    assert result.reason is None
    assert result.counters == expected_counters(gated=2, missing=2, projects=2)
    assert len(created) == 2
    assert {item["project"] for item in created} == {"sase", "other"}
    assert all(item["producer"] == {"chop": "plugins_required"} for item in created)
    assert all(item["request_id"].endswith("-g1") for item in created)
    state = _state(tmp_path)
    assert set(state["projects"]) == {"sase", "other"}
    assert state["projects"]["sase"]["generation"] == 1


def test_second_pass_with_unchanged_set_leaves_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = [missing_entry()]
    patch_projects(monkeypatch, tmp_path, missing)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    first = plugins_required._run(make_runtime(tmp_path))
    second = plugins_required._run(make_runtime(tmp_path))

    assert first.counters == expected_counters(gated=1, missing=1)
    assert second.counters == expected_counters(skipped=1, missing=1)
    assert len(created) == 1
    assert canceled == []


def test_answered_gate_is_not_reoffered_until_the_set_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = [missing_entry()]
    patch_projects(monkeypatch, tmp_path, missing)
    created = capture_created(monkeypatch)
    plugins_required._run(make_runtime(tmp_path))
    monkeypatch.setattr(plugins_required, "_gate_state", lambda _id: "terminal")

    second = plugins_required._run(make_runtime(tmp_path))

    assert second.counters == expected_counters(skipped=1, missing=1)
    assert len(created) == 1


def test_changed_missing_set_replaces_the_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_missing = [missing_entry()]
    patch_projects(monkeypatch, tmp_path, first_missing)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    plugins_required._run(make_runtime(tmp_path))

    second_missing = [
        missing_entry(),
        missing_entry(
            requirement="sase-research-artifacts",
            name="sase-research-artifacts",
            install_command="sase plugin install sase-research-artifacts",
        ),
    ]
    patch_projects(monkeypatch, tmp_path, second_missing)
    monkeypatch.setattr(
        plugins_required,
        "create_plugins_required_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(
        plugins_required,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
    )

    replaced = plugins_required._run(make_runtime(tmp_path))

    assert replaced.counters == expected_counters(gated=1, canceled=1, missing=2)
    assert len(created) == 2
    assert canceled[0][1] == "required_set_changed"
    assert created[1]["request_id"].endswith("-g2")


def test_satisfied_set_cancels_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(monkeypatch, tmp_path, [missing_entry()])
    capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    plugins_required._run(make_runtime(tmp_path))

    patch_projects(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        plugins_required,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
    )

    result = plugins_required._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(canceled=1)
    assert canceled[-1][1] == "required_plugins_satisfied"
    assert _state(tmp_path) == {} or _state(tmp_path).get("projects") == {}


def test_unreadable_project_does_not_cancel_a_healthy_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(monkeypatch, tmp_path, [missing_entry()])
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    plugins_required._run(make_runtime(tmp_path))

    def fail_collect(checkout: Path, *, inventory: object) -> tuple[None, str]:
        del checkout, inventory
        return None, "parse error"

    monkeypatch.setattr(plugins_required, "_collect_missing", fail_collect)

    result = plugins_required._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(projects=0)
    assert len(created) == 1
    assert canceled == []
    assert "sase" in _state(tmp_path)["projects"]


def test_two_projects_same_missing_set_raise_two_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = [missing_entry()]
    patch_projects(
        monkeypatch,
        tmp_path,
        {"sase": missing, "research": missing},
    )
    created = capture_created(monkeypatch)

    result = plugins_required._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=2, missing=2, projects=2)
    assert {item["request_id"] for item in created} == {
        created[0]["request_id"],
        created[1]["request_id"],
    }
    assert created[0]["request_id"] != created[1]["request_id"]
