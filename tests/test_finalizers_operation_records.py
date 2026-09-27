"""Coverage for uniform schema-v1 operation records (sase-1b2.5)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.finalizers.commit_repair_stitch import record_stitch_artifacts
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.operation_records import (
    OPERATION_RECORD_SCHEMA_VERSION,
    OperationRecorder,
    _operation_filename,
)
from sase.finalizers.progress import ProgressJournal, _journal_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def _journal_events(artifacts_dir: Path) -> list[dict]:
    lines = _journal_path(artifacts_dir).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_operation_filename_attempt_and_preflight() -> None:
    assert _operation_filename(1, "stitch main") == "attempt-1.stitch_main.outcome.json"
    assert _operation_filename(None, "describe") == "preflight.describe.outcome.json"


def test_recorder_writes_schema_v1_and_journal_events(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    journal = ProgressJournal(str(artifacts))
    notes: list[tuple] = []

    class _Tracker:
        def note_op(self, instance_id: str, op: str) -> None:
            notes.append((instance_id, op))

        def flush_pending_step(self, instance_id: str) -> None:
            notes.append(("flush", instance_id))

    recorder = OperationRecorder(
        str(artifacts), "check", journal=journal, tracker=_Tracker()
    )
    started = recorder.start("run", kind="subprocess", label="just check", attempt=1)
    recorder.finish(
        "run",
        kind="subprocess",
        label="just check",
        attempt=1,
        started_at=started,
        duration_seconds=1.5,
        argv=["just", "check"],
        returncode=0,
        logs={"stdout": "attempt-1.stdout"},
    )

    outcome = json.loads(
        (artifacts / "finalizers" / "check" / "attempt-1.run.outcome.json").read_text(
            encoding="utf-8"
        )
    )
    assert outcome["schema_version"] == OPERATION_RECORD_SCHEMA_VERSION
    assert outcome["op"] == "run"
    assert outcome["kind"] == "subprocess"
    assert outcome["label"] == "just check"
    assert outcome["attempt"] == 1
    assert outcome["argv"] == ["just", "check"]
    assert outcome["returncode"] == 0

    events = _journal_events(artifacts)
    assert [e["event"] for e in events] == ["op_started", "op_finished"]
    assert events[0]["op"] == "run"
    assert events[1]["returncode"] == 0
    assert ("check", "just check") in notes


def test_record_stitch_artifacts_extends_outcome_and_journals(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    journal = ProgressJournal(str(artifacts))
    context = FinalizerExecutionContext(
        artifacts_dir=str(artifacts), plan_digest=None, journal=journal
    )
    repo = DirtyRepo(name="main", path=str(tmp_path), changed_files=(), kind="main")
    result = StitchCommandResult(
        returncode=0, stdout="ok\n", stderr="", duration_seconds=2.0
    )

    record_stitch_artifacts(context, "commit", 1, result, label=repo.name)

    outcome = json.loads(
        (artifacts / "finalizers" / "commit" / "attempt-1.main.outcome.json").read_text(
            encoding="utf-8"
        )
    )
    assert outcome["schema_version"] == 1
    assert outcome["op"] == "main"
    assert outcome["kind"] == "subprocess"
    assert outcome["attempt"] == 1
    # Legacy keys are preserved for existing readers.
    assert outcome["returncode"] == 0
    assert "message_file" in outcome
    assert outcome["logs"]["stdout"] == "attempt-1.main.stdout"

    events = _journal_events(artifacts)
    assert [e["event"] for e in events] == ["op_started", "op_finished"]
    assert events[0]["instance_id"] == "commit"


def test_conflict_repair_uses_instance_id(tmp_path: Path) -> None:
    from sase.finalizers.commit_repair_conflict import (
        _conflict_repair_spent,
        run_conflict_repair_turn,
    )

    artifacts = tmp_path / "artifacts"
    repo = DirtyRepo(name="main", path=str(tmp_path), changed_files=(), kind="main")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")

    run_conflict_repair_turn(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
        options=None,
        repo=repo,
        instance_id="commit",
        attempt=1,
    )

    # The default instance id keeps the historical layout.
    assert (artifacts / "finalizers" / "commit").is_dir()
    assert not _conflict_repair_spent(str(artifacts), repo, instance_id="other")
    assert _conflict_repair_spent(str(artifacts), repo, instance_id="commit")

    outcome = json.loads(
        (
            artifacts
            / "finalizers"
            / "commit"
            / "attempt-1.conflict-repair-main.outcome.json"
        ).read_text(encoding="utf-8")
    )
    assert outcome["kind"] == "model_turn"
    assert outcome["attempt"] == 1
    assert "prompt" in outcome and "response" in outcome
