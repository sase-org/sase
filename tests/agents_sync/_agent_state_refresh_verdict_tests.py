from __future__ import annotations

import json
import time
from pathlib import Path

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.agent_state_refresh_memo import (
    AgentStateRefreshVerdictMemo,
    UnresolvedVerdictMemoEntry,
)
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import StateRepairReport
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._agent_state_refresh_test_support import (
    OWNER,
    FINISHED,
    STARTED,
    owner_identity,
    setup_refresh_repo,
    targets_for,
)


def _global_name(local: str, owner: AgentOwnerIdentity = OWNER) -> str:
    return f"{owner.username}.{owner.machine_name}.{local}"


def test_unchanged_unresolved_verdict_is_logged_once_and_changed_evidence_relogs(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.agents_sync import agent_state_refresh_memo as refresh_memo
    from sase.core import agent_scan_facade
    from sase.core.agent_run_state_wire import (
        AGENT_RUN_STATE_EVIDENCE_DISMISSED,
        AGENT_RUN_STATE_OBSERVATION_PRESENT,
        AgentRunStateRawObservationWire,
    )

    _remote, sync_target = setup_refresh_repo(
        tmp_path, runs=[("foo", "foo.job", "run-1", "completed")]
    )
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "ace-run" / "20260723120000"
    artifact_dir.mkdir(parents=True)
    for filename in (
        "agent_meta.json",
        "done.json",
        "waiting.json",
        "pending_question.json",
    ):
        (artifact_dir / filename).write_text("{}", encoding="utf-8")
    archive_root = tmp_path / "dismissed"
    archive_root.mkdir()
    (archive_root / "index.sqlite").write_bytes(b"index-v1")
    artifact_index = tmp_path / "agent-index.sqlite"
    artifact_index.write_bytes(b"agent-index-v1")

    monkeypatch.setattr(refresh_memo, "_projects_root", lambda: projects_root)
    monkeypatch.setattr(refresh_memo, "_dismissed_root", lambda: archive_root)
    monkeypatch.setattr(
        refresh_memo,
        "locate_artifact_dirs_for_run",
        lambda *_args: ((artifact_dir.resolve(),), None),
    )
    monkeypatch.setattr(
        agent_scan_facade,
        "default_agent_artifact_index_path",
        lambda: artifact_index,
    )

    record = V2RunRecord(
        "run-1", "foo.job", _global_name("foo.job"), "completed", STARTED, FINISHED
    )
    diagnostic = f"{record.global_name}: missing_evidence; preserved completed"
    dismissed_observation = AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
        read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
    )
    evaluations: list[str] = []

    def repair_one(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        memo = kwargs["unresolved_verdict_memo"]
        if memo.should_skip(target, record):
            return StateRepairReport(
                target.project_key,
                target.project,
                "apply",
                examined=1,
                unresolved=1,
                pass_complete=True,
            )
        evaluations.append(record.source_run_id)
        memo.record_unresolved(
            target,
            record,
            owner,
            "missing_evidence",
            (dismissed_observation,),
        )
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            unresolved=1,
            pass_complete=True,
            diagnostics=(diagnostic,),
        )

    common = {
        "state_dir": tmp_path / "state",
        "list_targets": targets_for([sync_target]),
        "require_owner": owner_identity,
        "repair_one": repair_one,
    }
    first = run_agent_state_refresh(**common, now_ms=1_000)
    second = run_agent_state_refresh(**common, now_ms=2_000)
    third = run_agent_state_refresh(**common, now_ms=3_000)

    assert first.diagnostics == (diagnostic,)
    assert second.diagnostics == third.diagnostics == ()
    assert second.unchanged_unresolved == third.unchanged_unresolved == 1
    assert second.daily_unchanged_unresolved == 1
    assert third.daily_unchanged_unresolved == 0
    assert evaluations == ["run-1"]

    with (artifact_dir / "done.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    changed = run_agent_state_refresh(**common, now_ms=4_000)
    assert changed.diagnostics == (diagnostic,)
    assert changed.unchanged_unresolved == 0
    assert evaluations == ["run-1", "run-1"]


def test_completed_verdict_pass_prunes_entries_for_runs_that_left_the_window() -> None:
    current = V2RunRecord("run-current", "foo.job", "alice.athena.foo.job", "completed")
    owner = OWNER
    current_key = json.dumps(
        ["proj", "alice@athena", "run-current"], separators=(",", ":")
    )
    stale_key = json.dumps(
        ["proj", "alice@athena", "run-left-window"], separators=(",", ":")
    )

    def entry(run_id: str) -> UnresolvedVerdictMemoEntry:
        return UnresolvedVerdictMemoEntry(
            project="proj",
            owner="alice@athena",
            source_run_id=run_id,
            evidence_fingerprint="evidence",
            preflight_fingerprint="preflight",
            verdict="missing_evidence",
            artifact_dirs=(),
            seen_generation=1,
            updated_at_ms=1,
        )

    entries = {
        current_key: entry("run-current"),
        stale_key: entry("run-left-window"),
    }
    memo = AgentStateRefreshVerdictMemo(
        entries,
        project="proj",
        owner=owner,
        generation=2,
        now_ms=2,
    )
    memo.mark_seen(current)
    memo.prune_completed_pass()

    assert current_key in entries
    assert stale_key not in entries


def test_unchanged_verdict_skips_filesystem_and_dismissed_lookups(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.agents_sync import _publication_state_repair_evidence as evidence
    from sase.agents_sync import _publication_state_repair_observations as observations

    _remote, sync_target = setup_refresh_repo(
        tmp_path, runs=[("foo", "foo.job", "run-1", "completed")]
    )
    record = V2RunRecord(
        "run-1", "foo.job", _global_name("foo.job"), "completed", STARTED, FINISHED
    )

    class SkipMemo:
        def mark_seen(self, _record):
            return None

        def should_skip(self, _target, _record):
            return True

    def unexpected_lookup(*_args):
        raise AssertionError("unchanged verdict should skip filesystem lookup")

    monkeypatch.setattr(
        observations, "filesystem_observations_for_run", unexpected_lookup
    )
    resolved = evidence._resolve_selected(  # noqa: SLF001
        sync_target,
        OWNER,
        {("foo", "run-1"): (record.global_name, record)},
        None,
        [("foo", "run-1")],
        time.monotonic() + 10,
        unresolved_verdict_memo=SkipMemo(),
    )

    assert resolved.unresolved == 1
    assert resolved.unchanged_unresolved == 1
    assert resolved.diagnostics == []


def test_corrupt_verdict_memo_entry_is_ignored(tmp_path: Path) -> None:
    _remote, sync_target = setup_refresh_repo(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "agent_state_refresh.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": {},
                "unresolved_verdicts": {"bad-entry": {"verdict": 7}},
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def repair_one(
        target: ProjectTarget, owner_identity: AgentOwnerIdentity, **_kwargs
    ):
        calls.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            pass_complete=True,
        )

    summary = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_one,
    )

    assert summary.errors == 0
    assert calls == [sync_target.project_key]
