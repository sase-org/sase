"""Live agent meta is the only ``%auto`` source (bead sase-15s).

After the TUI ``A`` toggle strips the auto keys from ``agent_meta.json``,
the plan/question auto readers must report no auto even though the live
runner process still exports the ``SASE_AGENT_AUTO_*`` launch-time
snapshot, and no runner write-back may resurrect the stripped keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.axe.agent_meta import overlay_live_auto_keys
from sase.axe.run_agent_markers import (
    persist_refreshed_clan_summary,
    record_run_started_at,
)
from sase.axe.run_agent_runner_refresh import reconcile_prompt_with_live_auto_state
from sase.axe.run_agent_wait_markers import record_wait_completed_at
from sase.main.plan_approve_handler import (
    get_auto_plan_approval_action,
    get_auto_plan_approval_argument,
    is_auto_approve_active,
)

_AUTO_ENV = {
    "SASE_AGENT_AUTO_APPROVE": "1",
    "SASE_AGENT_AUTO_APPROVE_PLAN_ACTION": "approve",
    "SASE_AGENT_AUTO_PLAN_ACTION": "approve",
    "SASE_AGENT_AUTO_APPROVE_ARGUMENT": "",
    "SASE_AGENT_AUTO_PLAN_ARGUMENT": "",
}


@pytest.fixture
def live_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the readers at a fresh artifacts dir with the env snapshot set."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    for name, value in _AUTO_ENV.items():
        monkeypatch.setenv(name, value)
    return artifacts


def _write_meta(artifacts: Path, meta: dict[str, object]) -> None:
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_env_snapshot_without_meta_keys_means_no_auto(
    live_artifacts: Path,
) -> None:
    """The sase-15s repro: env says auto, toggled meta says nothing."""
    _write_meta(live_artifacts, {"name": "agent-x"})

    assert get_auto_plan_approval_action() is None
    assert get_auto_plan_approval_argument() is None
    assert is_auto_approve_active() is False


def test_missing_meta_means_no_auto(live_artifacts: Path) -> None:
    assert get_auto_plan_approval_action() is None
    assert is_auto_approve_active() is False


def test_non_dict_meta_means_no_auto(live_artifacts: Path) -> None:
    (live_artifacts / "agent_meta.json").write_text("[1, 2]", encoding="utf-8")

    assert get_auto_plan_approval_action() is None
    assert is_auto_approve_active() is False


def test_bare_auto_meta_still_enables_approve(live_artifacts: Path) -> None:
    _write_meta(live_artifacts, {"approve": True})

    assert get_auto_plan_approval_action() == "approve"
    assert is_auto_approve_active() is True


def test_tale_argument_meta_enables_tale(live_artifacts: Path) -> None:
    _write_meta(
        live_artifacts,
        {"approve": True, "auto_approve_argument": "tale"},
    )

    assert get_auto_plan_approval_action() == "tale"
    assert get_auto_plan_approval_argument() == "tale"
    assert is_auto_approve_active() is True


def test_overlay_drops_memory_keys_stripped_from_disk(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})
    memory = {
        "approve": True,
        "auto_approve_plan_action": "tale",
        "auto_approve_argument": "tale",
    }

    overlay_live_auto_keys(str(artifacts), memory)

    assert memory == {}


def test_overlay_restores_disk_keys_missing_from_memory(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"approve": True, "auto_approve_argument": "tale"})
    memory: dict[str, object] = {"name": "agent-x"}

    overlay_live_auto_keys(str(artifacts), memory)

    assert memory["approve"] is True
    assert memory["auto_approve_argument"] == "tale"


def test_overlay_without_disk_file_leaves_memory_alone(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    memory = {"approve": True}

    overlay_live_auto_keys(str(artifacts), memory)

    assert memory == {"approve": True}


def test_overlay_with_corrupt_disk_leaves_memory_alone(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("not json", encoding="utf-8")
    memory = {"approve": True}

    overlay_live_auto_keys(str(artifacts), memory)

    assert memory == {"approve": True}


def _stale_bare_auto_memory() -> dict[str, object]:
    return {"name": "agent-x", "approve": True}


def test_run_started_write_keeps_toggle_off(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})

    record_run_started_at(str(artifacts), _stale_bare_auto_memory())

    disk = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "approve" not in disk


def test_wait_completed_write_keeps_toggle_off(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})

    record_wait_completed_at(str(artifacts), _stale_bare_auto_memory())

    disk = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "approve" not in disk


def test_clan_summary_refresh_keeps_toggle_off(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})

    persist_refreshed_clan_summary(str(artifacts), _stale_bare_auto_memory(), "summary")

    disk = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "approve" not in disk
    assert disk["clan_summary"] == "summary"


def test_refresh_reconcile_strips_stale_auto_after_toggle_off(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto\nDo the thing", str(artifacts)
    )

    assert "%auto" not in reconciled
    assert "Do the thing" in reconciled


def test_refresh_reconcile_restores_auto_after_toggle_on(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"approve": True})

    reconciled = reconcile_prompt_with_live_auto_state("Do the thing", str(artifacts))

    assert reconciled.startswith("%auto")
    assert "Do the thing" in reconciled


def test_refresh_reconcile_keeps_live_tale_mode(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(
        artifacts,
        {"approve": True, "auto_approve_argument": "tale"},
    )

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto:tale\nDo the thing", str(artifacts)
    )

    assert "%auto:tale" in reconciled


def test_refresh_reconcile_without_artifacts_dir_passes_through() -> None:
    prompt = "%auto\nDo the thing"

    assert reconcile_prompt_with_live_auto_state(prompt, None) == prompt


def test_refresh_reconcile_keeps_live_plan_mode(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(
        artifacts,
        {"approve": True, "auto_approve_argument": "plan"},
    )

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto\nDo the thing", str(artifacts)
    )

    assert "%auto:plan" in reconciled
    assert "\nDo the thing" in reconciled


def test_refresh_reconcile_bare_meta_keeps_bare_auto(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"approve": True})

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto:plan\nDo the thing", str(artifacts)
    )

    assert reconciled.startswith("%auto\n") or reconciled.startswith("%auto ")
    assert "%auto:" not in reconciled.split("\n")[0]


def test_refresh_reconcile_toggle_off_strips_plan_spelling(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto:plan\nDo the thing", str(artifacts)
    )

    assert "%auto" not in reconciled
    assert "Do the thing" in reconciled


def test_refresh_reconcile_legacy_argument_never_widens_to_bare(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"auto_approve_argument": "off"})

    reconciled = reconcile_prompt_with_live_auto_state(
        "%auto:plan\nDo the thing", str(artifacts)
    )

    assert "%auto" not in reconciled
    assert "Do the thing" in reconciled


def test_failed_disk_read_keeps_memory_auto_keys(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("not json", encoding="utf-8")
    memory: dict[str, object] = {
        "approve": True,
        "auto_approve_argument": "tale",
        "auto_approve_plan_action": "tale",
    }

    record_run_started_at(str(artifacts), memory)
    assert memory.get("approve") is True
    assert memory.get("auto_approve_argument") == "tale"

    memory2: dict[str, object] = {
        "approve": True,
        "auto_approve_argument": "tale",
    }
    record_wait_completed_at(str(artifacts), memory2)
    assert memory2.get("approve") is True
    assert memory2.get("auto_approve_argument") == "tale"

    memory3: dict[str, object] = {
        "approve": True,
        "auto_approve_argument": "tale",
    }
    persist_refreshed_clan_summary(str(artifacts), memory3, "summary")
    assert memory3.get("approve") is True
    assert memory3.get("auto_approve_argument") == "tale"


def test_missing_disk_read_keeps_memory_auto_keys(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    memory: dict[str, object] = {
        "approve": True,
        "auto_approve_argument": "tale",
    }

    record_run_started_at(str(artifacts), memory)

    assert memory.get("approve") is True
    assert memory.get("auto_approve_argument") == "tale"


def test_full_overwrite_write_backs_keep_toggle_off(tmp_path: Path) -> None:
    """The launch write-back pattern never resurrects toggled-off auto."""
    from sase.axe.agent_meta import overlay_live_auto_keys
    from sase.axe.run_agent_markers import write_agent_meta

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})
    stale: dict[str, object] = {
        "name": "agent-x",
        "approve": True,
        "auto_approve_plan_action": "tale",
        "auto_approve_argument": "tale",
    }

    overlay_live_auto_keys(str(artifacts), stale)
    write_agent_meta(str(artifacts), stale)

    disk = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "approve" not in disk
    assert "auto_approve_plan_action" not in disk
    assert "auto_approve_argument" not in disk


def test_toggle_off_makes_next_plan_gate_manual(
    live_artifacts: Path,
) -> None:
    """The sase-15s scenario: after an A toggle, the next gate is manual."""
    from sase.plan_gate import build_plan_approval_gate_spec
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    _write_meta(live_artifacts, {"approve": True})
    assert is_auto_approve_active() is True

    # The A toggle strips the auto keys, as sase agent persist-directive does.
    _write_meta(live_artifacts, {"name": "agent-x"})
    assert is_auto_approve_active() is False
    assert get_auto_plan_approval_action() is None
    assert get_auto_plan_approval_argument() is None

    plan = live_artifacts / "next.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    spec = build_plan_approval_gate_spec(
        plan,
        "toggle-off-session",
        auto_enabled=is_auto_approve_active(),
        auto_argument=get_auto_plan_approval_argument(),
    )

    assert spec["auto"]["enabled"] is False


def test_toggle_off_on_disk_clears_memory_auto_keys(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_meta(artifacts, {"name": "agent-x"})
    memory: dict[str, object] = {
        "name": "agent-x",
        "approve": True,
        "auto_approve_plan_action": "tale",
        "auto_approve_argument": "tale",
    }

    record_run_started_at(str(artifacts), memory)

    assert "approve" not in memory
    assert "auto_approve_plan_action" not in memory
    assert "auto_approve_argument" not in memory

    _write_meta(artifacts, {"name": "agent-x"})
    memory2: dict[str, object] = {
        "name": "agent-x",
        "approve": True,
        "auto_approve_argument": "tale",
    }
    record_wait_completed_at(str(artifacts), memory2)

    assert "approve" not in memory2
    assert "auto_approve_argument" not in memory2

    _write_meta(artifacts, {"name": "agent-x"})
    memory3: dict[str, object] = {
        "name": "agent-x",
        "approve": True,
        "auto_approve_argument": "tale",
    }
    persist_refreshed_clan_summary(str(artifacts), memory3, "summary")

    assert "approve" not in memory3
    assert "auto_approve_argument" not in memory3
