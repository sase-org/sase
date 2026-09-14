"""Manual monitor resume recovery-branch tests."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.monitor.resume as resume_module
from sase.monitor.continuation_delivery import (
    DELIVERY_ARTIFACTS_ENV,
    DELIVERY_CRASH_ENV,
    DELIVERY_IDENTITY_ENV,
    DELIVERY_KEY_ENV,
    _InjectedDeliveryCrash,
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
)
from sase.monitor.delivery import (
    delivery_key,
    load_delivery_record,
    update_delivery_workspace,
)
from sase.monitor.resume import MonitorResumeError, resume_monitor

from ._resume_fixtures import (
    _fake_spawn,
    _sandbox_home as _sandbox_home,
    _terminal_monitor,
)


def test_checkpoint_resume_creates_numbered_manual_branch_and_supersedes_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    base_key = delivery_key(
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
    )
    claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(
        record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
    )

    assert result.manual_revision is True
    assert result.branch == "manual-recovery-1"
    assert len(captured) == 1
    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"
    manual_key = json.loads(captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert manual_key["branch"] == "manual-recovery-1"
    prompt = captured[0]["prompt"]
    assert "## Continuation checkpoint" in prompt
    assert "recover safely" in prompt
    assert '"coverage": [' in prompt
    assert "| **Outcome** | FAILED — exit 1 |" in prompt
    assert (
        Path(monitor_dir) / "continuation" / "manual_resume" / "manual-recovery-1.json"
    ).exists()
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["continuation_intent_id"].endswith(
        on_disk["continuation_intent_id"].split(":")[-1]
    )
    assert on_disk["continuation_checkpoint_ref"].startswith("local:continuation/")


def test_checkpoint_resume_preserves_concurrent_acknowledgment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, monitor_dir)
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    original = resume_module._apply_resume_adoption  # noqa: SLF001

    def adopt_then_apply(*args: Any, **kwargs: Any) -> Any:
        adopted = adopt_ordinary_continuation_delivery()
        assert adopted is not None
        assert adopted["disposition"] == "acknowledged"
        assert adopted["acknowledged_by"] == "acme--1"
        return original(*args, **kwargs)

    monkeypatch.setattr(resume_module, "_apply_resume_adoption", adopt_then_apply)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )

    with pytest.raises(MonitorResumeError, match="already been acknowledged"):
        resume_monitor(record, checkpoint_path=str(checkpoint), model="codex/gpt-5")

    old = load_delivery_record(monitor_dir, claim.key)
    assert old is not None
    assert old["disposition"] == "acknowledged"
    assert old["acknowledged_by"] == "acme--1"
    assert captured == []


def test_resume_refuses_stale_receiver_without_live_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    update_delivery_workspace(monitor_dir, claim.key, workspace_identity=str(tmp_path))
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    with pytest.raises(MonitorResumeError, match="ambiguous"):
        resume_monitor(record)

    payload = load_delivery_record(monitor_dir, claim.key)
    assert payload is not None
    assert payload["disposition"] == "needs_attention"
    assert payload.get("acknowledged_by") in {None, "acme--1"}
    assert captured == []


def test_concurrent_identical_checkpoint_resume_spawns_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    started = threading.Barrier(2)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        started.wait(timeout=5)
        try:
            results.append(
                resume_monitor(
                    record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(captured) == 1
    assert results
    assert all(item.launched for item in results)
    assert {item.branch for item in results} <= {"manual-recovery-1"}
    assert all(
        isinstance(exc, MonitorResumeError) and exc.code == "ambiguous_receiver"
        for exc in errors
    )


def test_crash_after_fence_keeps_acknowledged_branch_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    base_key = delivery_key(
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
    )
    claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    monkeypatch.setenv(DELIVERY_CRASH_ENV, "after_resume_fence")

    with pytest.raises(_InjectedDeliveryCrash, match="after_resume_fence"):
        resume_monitor(record, checkpoint_path=str(checkpoint), model="codex/gpt-5")

    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"
    monkeypatch.delenv(DELIVERY_CRASH_ENV, raising=False)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    result = resume_monitor(
        record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
    )
    assert result.spawned is True
    assert result.branch == "manual-recovery-1"
    assert len(captured) == 1
    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"
