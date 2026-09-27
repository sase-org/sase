"""Coverage for the controller progress journal and row-summary writer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import (
    GATE_PENDING_MARKER,
    MONITOR_PENDING_MARKER,
    PENDING_HANDOFF_MARKERS,
    PIPE_PENDING_MARKER,
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
    has_pending_handoff,
    pending_handoff_kind,
)
from sase.finalizers.config import FinalizerConfig
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.plan import (
    FINALIZER_PLAN_FILENAME,
    resolve_and_persist_finalizer_plan,
)
from sase.finalizers.progress import (
    PROGRESS_JOURNAL_MAX_BYTES,
    ProgressJournal,
    journal_path,
)
from sase.finalizers.status_summary import FinalizerStatusTracker
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


def _journal_events(artifacts_dir: Path) -> list[dict[str, Any]]:
    lines = (journal_path(artifacts_dir)).read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _read_meta(artifacts_dir: Path) -> dict[str, Any]:
    return json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("marker", "kind"),
    [
        (PLAN_PENDING_MARKER, "plan"),
        (QUESTIONS_PENDING_MARKER, "questions"),
        (MONITOR_PENDING_MARKER, "monitor"),
        (GATE_PENDING_MARKER, "gate"),
        (PIPE_PENDING_MARKER, "pipe"),
    ],
)
def test_pending_handoff_kind_per_marker(
    tmp_path: Path, marker: str, kind: str
) -> None:
    (tmp_path / marker).write_text("pending", encoding="utf-8")

    assert pending_handoff_kind(str(tmp_path)) == kind
    assert has_pending_handoff(str(tmp_path)) is True


def test_pending_handoff_kind_absent(tmp_path: Path) -> None:
    assert pending_handoff_kind(str(tmp_path)) is None
    assert pending_handoff_kind(None) is None
    assert has_pending_handoff(str(tmp_path)) is False
    assert has_pending_handoff(None) is False


def test_pending_handoff_markers_tuple_unchanged() -> None:
    assert PENDING_HANDOFF_MARKERS == (
        PLAN_PENDING_MARKER,
        QUESTIONS_PENDING_MARKER,
        MONITOR_PENDING_MARKER,
        GATE_PENDING_MARKER,
        PIPE_PENDING_MARKER,
    )


def test_journal_appends_sequenced_records(tmp_path: Path) -> None:
    journal = ProgressJournal(str(tmp_path))
    journal.record("phase_started", run_id="abc")
    journal.record("cycle_started", cycle=1)

    events = _journal_events(tmp_path)
    assert [item["event"] for item in events] == ["phase_started", "cycle_started"]
    assert [item["seq"] for item in events] == [1, 2]
    assert all(item["v"] == 1 and isinstance(item["t"], float) for item in events)
    assert events[0]["run_id"] == "abc"


def test_journal_continues_seq_across_instances(tmp_path: Path) -> None:
    first = ProgressJournal(str(tmp_path))
    first.record("phase_started")
    second = ProgressJournal(str(tmp_path))
    second.record("cycle_started")

    events = _journal_events(tmp_path)
    assert [item["seq"] for item in events] == [1, 2]


def test_journal_falls_back_to_line_count_on_malformed_tail(
    tmp_path: Path,
) -> None:
    path = journal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json\n{bad}\n", encoding="utf-8")

    ProgressJournal(str(tmp_path)).record("cycle_started")

    events = _journal_events(tmp_path)
    assert events[-1]["seq"] == 3


def test_journal_is_best_effort_without_dir() -> None:
    journal = ProgressJournal(None)

    assert journal.disabled is True
    journal.record("phase_started")


def test_journal_ceiling_writes_truncated_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = ProgressJournal(str(tmp_path))
    journal.record("phase_started", run_id="x")
    size = journal_path(tmp_path).stat().st_size
    monkeypatch.setattr(
        "sase.finalizers.progress.PROGRESS_JOURNAL_MAX_BYTES", size + 300
    )
    journal.record("cycle_started", cycle=1, detail="y" * 500)
    journal.record("cycle_started", cycle=2)

    events = _journal_events(tmp_path)
    kinds = [item["event"] for item in events]
    assert kinds == ["phase_started", "observability_truncated"]
    assert journal.disabled is True
    assert len(journal_path(tmp_path).read_bytes()) <= size + 300


def test_journal_max_bytes_default() -> None:
    assert PROGRESS_JOURNAL_MAX_BYTES == 256 * 1024


def test_tracker_seal_planned_shape(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")

    FinalizerStatusTracker(str(tmp_path)).seal_planned(
        plan_digest="digest-1", instance_ids=["commit", "check"]
    )

    summary = _read_meta(tmp_path)["finalizer_status"]
    assert summary["schema_version"] == 1
    assert summary["phase"] == "planned"
    assert summary["status"] is None
    assert summary["plan_digest"] == "digest-1"
    assert summary["instance_count"] == 2
    assert [item["id"] for item in summary["instances"]] == ["commit", "check"]
    assert all(item["status"] == "planned" for item in summary["instances"])


def test_tracker_empty_plan_writes_empty_instances(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")

    FinalizerStatusTracker(str(tmp_path)).seal_planned(
        plan_digest="digest-1", instance_ids=[]
    )

    summary = _read_meta(tmp_path)["finalizer_status"]
    assert summary["instances"] == []
    assert summary["instance_count"] == 0


def test_tracker_caps_instances_and_strings(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")

    tracker = FinalizerStatusTracker(str(tmp_path))
    tracker.seal_planned(
        plan_digest="d", instance_ids=[f"instance-{n}" for n in range(17)]
    )
    tracker.note_op("instance-0", "o" * 200, step="s" * 200)

    summary = _read_meta(tmp_path)["finalizer_status"]
    assert len(summary["instances"]) == 16
    assert summary["instance_count"] == 17
    assert summary["instances"][0]["op"] == "o" * 120
    assert summary["instances"][0]["step"] == "s" * 120


def test_tracker_step_writes_are_throttled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")
    writes: list[str] = []
    real_update = None
    import sase.axe.run_agent_helpers as helpers

    real_update = helpers.update_meta_field

    def _counting(artifacts_dir: str, key: str, value: Any) -> None:
        writes.append(key)
        real_update(artifacts_dir, key, value)

    monkeypatch.setattr(helpers, "update_meta_field", _counting)
    tracker = FinalizerStatusTracker(str(tmp_path))
    tracker.seal_planned(plan_digest="d", instance_ids=["commit"])
    before = len(writes)
    tracker.note_step("commit", "step one")
    tracker.note_step("commit", "step two")

    assert len(writes) == before + 1
    assert _read_meta(tmp_path)["finalizer_status"]["instances"][0]["step"] in {
        "step one",
        "step two",
    }
    tracker.note_op("commit", "run", step="final step")
    assert len(writes) == before + 2
    assert (
        _read_meta(tmp_path)["finalizer_status"]["instances"][0]["step"] == "final step"
    )


def test_tracker_mark_skipped_and_settled(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")
    tracker = FinalizerStatusTracker(str(tmp_path))
    tracker.mark_skipped(reason="handoff:plan")

    skipped = _read_meta(tmp_path)["finalizer_status"]
    assert skipped["phase"] == "skipped"
    assert skipped["reason"] == "handoff:plan"

    tracker.mark_settled(status="failed", reason="command_failed")

    settled = _read_meta(tmp_path)["finalizer_status"]
    assert settled["phase"] == "settled"
    assert settled["status"] == "failed"
    assert settled["reason"] == "command_failed"


def test_tracker_writer_failure_is_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_helpers as helpers

    def _boom(artifacts_dir: str, key: str, value: Any) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(helpers, "update_meta_field", _boom)
    tracker = FinalizerStatusTracker(str(tmp_path))
    tracker.seal_planned(plan_digest="d", instance_ids=["commit"])
    tracker.note_instance_started("commit")
    tracker.note_instance_finished("commit", status="success")
    tracker.mark_settled(status="success")


def _command_config(*, command: list[str]) -> FinalizerConfig:
    from sase.finalizers.config import (
        ConfiguredFinalizerInstance,
        FinalizerFieldProvenance,
    )

    return FinalizerConfig(
        defaults=("local-check",),
        required=(),
        instances={
            "local-check": ConfiguredFinalizerInstance(
                instance_id="local-check",
                provider_ref="builtin@command",
                config={
                    "command": command,
                    "cwd": "primary",
                    "timeout": "30s",
                    "submission": "none",
                },
                provenance={
                    "use": FinalizerFieldProvenance("test", None),
                },
            )
        },
        provenance={},
    )


def _prepare_command_run(monkeypatch: pytest.MonkeyPatch, artifacts: Path) -> None:
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config",
        lambda: _command_config(command=[sys.executable, "-c", "print('checked')"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=str(artifacts), repos=(), details=""),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))


def _run(artifacts: Path) -> Any:
    return run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def test_controller_success_journals_full_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(monkeypatch, artifacts)

    result = _run(artifacts)

    assert result.content == "done"
    kinds = [item["event"] for item in _journal_events(artifacts)]
    for expected in (
        "phase_started",
        "cycle_started",
        "declaration_started",
        "declaration_finished",
        "instance_started",
        "attempt_started",
        "attempt_finished",
        "instance_finished",
        "phase_finished",
    ):
        assert expected in kinds
    started = next(
        item for item in _journal_events(artifacts) if item["event"] == "phase_started"
    )
    assert started["mode"] == "normal"
    assert started["plan_digest"]
    assert started["runner"]["pid"] == os.getpid()
    finished = [
        item for item in _journal_events(artifacts) if item["event"] == "phase_finished"
    ]
    assert finished[-1]["status"] == "success"
    seqs = [item["seq"] for item in _journal_events(artifacts)]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    summary = _read_meta(artifacts)["finalizer_status"]
    assert summary["phase"] == "settled"
    assert summary["status"] == "success"
    assert summary["instances"][0]["status"] == "success"
    assert summary["instances"][0]["attempt"] == 1


def test_controller_failure_journals_failed_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config",
        lambda: _command_config(
            command=[sys.executable, "-c", "import sys; sys.exit(3)"]
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=str(artifacts), repos=(), details=""),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))

    with pytest.raises(RuntimeError):
        _run(artifacts)

    kinds = [item["event"] for item in _journal_events(artifacts)]
    assert kinds[-1] == "phase_finished"
    finished = [
        item for item in _journal_events(artifacts) if item["event"] == "phase_finished"
    ]
    assert finished[-1]["status"] == "failed"
    summary = _read_meta(artifacts)["finalizer_status"]
    assert summary["phase"] == "settled"
    assert summary["status"] == "failed"
    assert summary["instances"][0]["status"] == "failed"
    assert summary["instances"][0]["reason"]


def test_controller_empty_plan_writes_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(monkeypatch, artifacts)
    _, directives = extract_prompt_directives("%final:none\nDo work")
    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))

    result = _run(artifacts)

    assert result.content == "done"
    kinds = [item["event"] for item in _journal_events(artifacts)]
    assert "phase_started" in kinds
    assert kinds[-1] == "phase_finished"
    summary = _read_meta(artifacts)["finalizer_status"]
    assert summary["phase"] == "settled"
    assert summary["status"] == "success"
    assert summary["instances"] == []


def test_controller_integrity_failure_still_journals_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(monkeypatch, artifacts)
    payload = json.loads(
        (artifacts / FINALIZER_PLAN_FILENAME).read_text(encoding="utf-8")
    )
    payload["plan"]["plan_digest"] = "0" * 64
    (artifacts / FINALIZER_PLAN_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with pytest.raises(FinalizerControllerError):
        _run(artifacts)

    kinds = [item["event"] for item in _journal_events(artifacts)]
    assert kinds[-1] == "phase_finished"
    assert "phase_started" not in kinds


def test_controller_handoff_skip_journals_phase_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / PLAN_PENDING_MARKER).write_text("pending", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    sentinel = InvokeResult(content="untouched")

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=sentinel,
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result is sentinel
    events = _journal_events(artifacts)
    assert len(events) == 1
    assert events[0]["event"] == "phase_skipped"
    assert events[0]["reason"] == "handoff:plan"
    summary = _read_meta(artifacts)["finalizer_status"]
    assert summary["phase"] == "skipped"
    assert summary["reason"] == "handoff:plan"


def test_controller_handoff_skip_writes_nothing_without_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / PLAN_PENDING_MARKER).write_text("pending", encoding="utf-8")
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    sentinel = InvokeResult(content="untouched")

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=sentinel,
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result is sentinel
    assert not journal_path(artifacts).exists()


def test_controller_skip_writer_failure_leaves_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / PLAN_PENDING_MARKER).write_text("pending", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setattr(
        "sase.finalizers.progress.ProgressJournal.record",
        lambda self, event, **fields: (_ for _ in ()).throw(OSError("gone")),
    )
    import sase.axe.run_agent_helpers as helpers

    monkeypatch.setattr(
        helpers,
        "update_meta_field",
        lambda artifacts_dir, key, value: (_ for _ in ()).throw(OSError("gone")),
    )
    sentinel = InvokeResult(content="untouched")

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=sentinel,
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result is sentinel


def test_controller_run_writer_failure_leaves_result_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    _prepare_command_run(monkeypatch, clean)
    assert _run(clean).content == "done"
    expected = json.loads((clean / "finalizer_result.json").read_text())

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _prepare_command_run(monkeypatch, artifacts)
    monkeypatch.setattr(
        "sase.finalizers.progress.ProgressJournal.record",
        lambda self, event, **fields: None,
    )
    import sase.axe.run_agent_helpers as helpers

    monkeypatch.setattr(
        helpers,
        "update_meta_field",
        lambda artifacts_dir, key, value: (_ for _ in ()).throw(OSError("gone")),
    )

    result = _run(artifacts)

    def _normalized(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(json.dumps(payload))
        for instance in normalized.get("instances", []):
            instance["evidence"] = [
                item
                for item in instance.get("evidence", [])
                if item.get("kind") != "duration_seconds"
            ]
        return normalized

    assert result.content == "done"
    actual = json.loads((artifacts / "finalizer_result.json").read_text())
    assert _normalized(actual) == _normalized(expected)
