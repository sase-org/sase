"""Tests for the trigger phase: doorbell, scheduler sweep, waiter safety."""

from __future__ import annotations

import ast
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.wait_watch._classify import classify_wait_target
from sase.agent.wait_watch._types import WaitState, WaitTarget, WaitTargetKind
from sase.axe import runner_auto_restart_doorbell as doorbell_mod
from sase.axe.run_agent_runner_errors import RunnerErrorContext, record_runner_error
from sase.axe.run_agent_runner_finalize import write_error_done_marker
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (doorbells, ledger, storm state)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture
def failed_row(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts" / "ace-run" / "20261009T120000"
    artifacts.mkdir(parents=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "trigger-test-worker"}), encoding="utf-8"
    )
    return artifacts


def _error_context(artifacts: Path) -> RunnerErrorContext:
    return RunnerErrorContext(
        current_artifacts_dir=str(artifacts),
        cl_name="cl",
        project_file="/tmp/project.sase",
        timestamp="20261009_120000",
        artifacts_timestamp="20261009120000",
        workspace_num=1,
        workspace_dir=str(artifacts / "workspace"),
        output_path=str(artifacts / "output.log"),
        agent_name="trigger-test-worker",
        agent_model="model",
        agent_llm_provider="provider",
        agent_vcs_provider=None,
        agent_hidden=False,
        project_name="sase",
    )


def _kills() -> Any:
    return SimpleNamespace(labels=MagicMock(return_value=MagicMock()))


def _raise_import_error() -> BaseException:
    try:
        raise ImportError("cannot import name 'gone' from 'sase.somewhere'")
    except ImportError as exc:
        return exc
    raise AssertionError("unreachable")


# --- stdlib-only firewall ----------------------------------------------------


def test_doorbell_module_is_stdlib_only_with_no_local_imports() -> None:
    path = Path(doorbell_mod.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class ImportVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.top_level: list[str] = []
            self.nested: list[str] = []

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            self._record(node, [alias.name for alias in node.names])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            self._record(node, [node.module or ""])

        def _record(self, node: ast.AST, names: list[str]) -> None:
            in_function = any(
                isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node in ast.walk(parent)
                and node is not parent
                for parent in ast.walk(tree)
            )
            target = self.nested if in_function else self.top_level
            target.extend(names)

    visitor = ImportVisitor()
    visitor.visit(tree)
    assert visitor.nested == []
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for name in visitor.top_level:
        assert name.split(".")[0] in allowed, f"non-stdlib import: {name}"


def test_doorbell_roundtrip(tmp_home: Path, failed_row: Path) -> None:
    path = doorbell_mod.drop_doorbell(
        artifacts_dir=str(failed_row),
        project="sase",
        agent_name="trigger-test-worker",
    )
    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["artifacts_dir"] == str(failed_row)
    assert payload["skew_suspect"] is True

    assert (
        doorbell_mod.recovery_requests_silence(str(failed_row / "done.json")) is False
    )
    (failed_row / "done.json").write_text(
        json.dumps(
            {
                "outcome": "failed",
                "recovery": doorbell_mod.pending_recovery_payload(),
            }
        )
    )
    assert doorbell_mod.recovery_requests_silence(str(failed_row / "done.json")) is True


# --- failure-path doorbell under an import firewall --------------------------


class _ImportFirewall:
    def __init__(self) -> None:
        self.attempted: list[str] = []

    def find_module(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> object:
        if fullname == "sase" or fullname.startswith("sase."):
            self.attempted.append(fullname)
            raise ImportError(f"import-firewall: {fullname} imported late")
        return None


def _run_poisoned(func: Any) -> list[str]:
    firewall = _ImportFirewall()
    sys.meta_path.insert(0, firewall)
    try:
        func()
    finally:
        sys.meta_path.remove(firewall)
    return firewall.attempted


def test_failure_path_rings_doorbell_without_new_imports(
    tmp_home: Path, failed_row: Path
) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod

    def act() -> None:
        record_runner_error(
            _raise_import_error(),
            context=_error_context(failed_row),
            write_error_done_marker=write_error_done_marker,
            agent_kills=_kills(),
            message_prefix="Error running agent",
            auto_restart_enabled=True,
            killed=False,
        )

    assert _run_poisoned(act) == []
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    assert done["recovery"]["state"] == "pending"
    assert done["failure_facts"]["skew_suspect"] is True
    assert ledger_mod.list_doorbells() != []


def test_failure_path_silent_without_enable_bit(
    tmp_home: Path, failed_row: Path
) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod

    record_runner_error(
        _raise_import_error(),
        context=_error_context(failed_row),
        write_error_done_marker=write_error_done_marker,
        agent_kills=_kills(),
        message_prefix="Error running agent",
        auto_restart_enabled=False,
        killed=False,
    )
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    assert "recovery" not in done
    assert ledger_mod.list_doorbells() == []


def test_failure_path_no_doorbell_for_kills_or_real_bugs(
    tmp_home: Path, failed_row: Path
) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod

    record_runner_error(
        _raise_import_error(),
        context=_error_context(failed_row),
        write_error_done_marker=write_error_done_marker,
        agent_kills=_kills(),
        message_prefix="Error running agent",
        auto_restart_enabled=True,
        killed=True,
    )
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    assert "recovery" not in done
    assert ledger_mod.list_doorbells() == []

    try:
        raise ValueError("an ordinary bug")
    except ValueError as exc:
        record_runner_error(
            exc,
            context=_error_context(failed_row),
            write_error_done_marker=write_error_done_marker,
            agent_kills=_kills(),
            message_prefix="Error running agent",
            auto_restart_enabled=True,
            killed=False,
        )
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    assert "recovery" not in done
    assert ledger_mod.list_doorbells() == []


# --- scheduler sweep ---------------------------------------------------------


def _write_failed_row(artifacts: Path, *, pending: bool = True) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    done: dict[str, Any] = {"outcome": "failed", "error": "ImportError: boom"}
    if pending:
        done["recovery"] = {
            "state": "pending",
            "reason": None,
            "reason_text": "recovery pending",
            "requested_at": "2026-10-09T12:00:00+00:00",
            "updated_at": "2026-10-09T12:00:00+00:00",
            "episode_id": None,
        }
    (artifacts / "done.json").write_text(json.dumps(done), encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "sweep-test-worker"}), encoding="utf-8"
    )


def test_idle_tick_skips_full_scan(tmp_home: Path) -> None:
    from sase.agent.auto_restart import sweep as sweep_mod

    first = sweep_mod._collect_job_work(now=1000.0)
    assert first.full_scan is True
    assert first.actionable is False
    second = sweep_mod._collect_job_work(now=1001.0)
    assert second.full_scan is False
    assert second.targets == []


def test_disabled_tick_resurfaces_without_ledger(
    tmp_home: Path, tmp_path: Path
) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.agent.auto_restart.healer import HealerTarget

    row = tmp_path / "row" / "20261009T120000"
    _write_failed_row(row)
    target = HealerTarget(
        artifacts_dir=row, project="sase", agent_name="sweep-test-worker"
    )
    work = sweep_mod._JobWork(targets=[target])
    with patch("sase.agent.auto_restart.notify.resurface_failure", return_value=None):
        resurfaced = sweep_mod._resurface_for_disabled(work, reason="is disabled")
    assert resurfaced == 1
    done = json.loads((row / "done.json").read_text(encoding="utf-8"))
    assert done["recovery"]["state"] == "declined"
    assert ledger_mod.iter_ledger_records() == []


def _fake_launched_record(
    monkeypatch: pytest.MonkeyPatch, old: Path, new: Path
) -> list[str]:
    """Patch the ledger with one launched record; return collected events."""
    from sase.agent.auto_restart import ledger as ledger_mod

    stored = SimpleNamespace(
        record=SimpleNamespace(
            state="launched",
            key="sase__20261009T120000",
            failed_artifacts_dir=str(old),
            launched_artifacts_dir=str(new),
        ),
        extra={},
    )
    events: list[str] = []
    monkeypatch.setattr(ledger_mod, "iter_ledger_records", lambda: [stored])
    monkeypatch.setattr(
        ledger_mod,
        "advance_ledger_record",
        lambda record, event, **kwargs: events.append(event),
    )
    return events


def test_settle_launched_records(
    tmp_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.auto_restart import sweep as sweep_mod

    old = tmp_path / "old" / "20261009T120000"
    new = tmp_path / "new" / "20261009T130000"
    _write_failed_row(old)
    new.mkdir(parents=True)
    (new / "done.json").write_text(json.dumps({"outcome": "completed"}))
    events = _fake_launched_record(monkeypatch, old, new)
    assert sweep_mod._settle_launched_records() == 1
    assert events == ["settled_ok"]


def test_settle_launched_failed_replacement(
    tmp_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.auto_restart import sweep as sweep_mod

    old = tmp_path / "old" / "20261009T120000"
    new = tmp_path / "new" / "20261009T130000"
    _write_failed_row(old)
    new.mkdir(parents=True)
    (new / "done.json").write_text(json.dumps({"outcome": "failed"}))
    events = _fake_launched_record(monkeypatch, old, new)
    assert sweep_mod._settle_launched_records() == 1
    assert events == ["settled_failed"]


def test_proc_dedup(tmp_home: Path) -> None:
    from sase.agent.auto_restart import sweep as sweep_mod

    with patch("sase.procs.store.read_procs", return_value=[]):
        assert sweep_mod._proc_already_queued() is False
    queued = SimpleNamespace(concurrency_keys=["agent-auto-restart"])
    with patch("sase.procs.store.read_procs", return_value=[queued]):
        assert sweep_mod._proc_already_queued() is True


def test_run_job_tick_disabled(tmp_home: Path, tmp_path: Path) -> None:
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.agent.auto_restart.healer import HealerTarget

    row = tmp_path / "row" / "20261009T120000"
    _write_failed_row(row)
    doorbell_mod.drop_doorbell(
        artifacts_dir=str(row), project="sase", agent_name="sweep-test-worker"
    )
    with (
        patch(
            "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
            return_value=False,
        ),
        patch("sase.agent.auto_restart.notify.resurface_failure", return_value=None),
    ):
        tick = sweep_mod.run_job_tick(now=time.time())
    assert tick.action == "disabled"
    assert tick.resurfaced >= 1
    done = json.loads((row / "done.json").read_text(encoding="utf-8"))
    assert done["recovery"]["state"] == "declined"


# --- waiter safety -----------------------------------------------------------


def _agent_target(artifacts: Path) -> WaitTarget:
    return WaitTarget(
        raw_name="pinned",
        name="pinned",
        kind=WaitTargetKind.AGENT,
        artifact_dir=str(artifacts),
        project_name="sase",
    )


def _snapshot(*records: AgentArtifactRecordWire) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=list(records),
    )


def _record(timestamp: str, artifacts: str, *, outcome: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir="/tmp/sase/projects/sase",
        project_file="/tmp/sase/projects/sase/sase.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifacts,
        timestamp=timestamp,
        agent_meta=AgentMetaWire(name="pinned", run_started_at="2026-10-09T12:00:00Z"),
        done=DoneMarkerWire(outcome=outcome),
        has_done_marker=True,
    )


def test_missing_target_stays_parked_while_recovery_in_flight(
    tmp_home: Path, tmp_path: Path
) -> None:
    old = tmp_path / "old" / "20261009T120000"
    _write_failed_row(old, pending=True)
    state = classify_wait_target(_agent_target(old), ())
    assert state.state is WaitState.WAITING
    assert state.reason == "auto-restart recovery in flight"

    done = json.loads((old / "done.json").read_text(encoding="utf-8"))
    done["recovery"]["state"] = "declined"
    (old / "done.json").write_text(json.dumps(done), encoding="utf-8")
    state = classify_wait_target(_agent_target(old), ())
    assert state.state is WaitState.STALLED
    assert state.reason == "target artifact is missing"


def test_missing_target_follows_replacement(
    tmp_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.auto_restart import forward as forward_mod

    old = tmp_path / "old" / "20261009T120000"
    new = tmp_path / "new" / "20261009T130000"
    _write_failed_row(old)
    new.mkdir(parents=True)
    _fake_launched_record(monkeypatch, old, new)
    assert forward_mod.find_replacement_artifacts_dir(str(old)) == str(new)
    assert forward_mod.recovery_in_flight(str(old)) is True

    snapshot = _snapshot(_record("20261009T130000", str(new), outcome="completed"))
    state = classify_wait_target(_agent_target(old), snapshot.records)
    assert state.state is WaitState.SUCCEEDED
    assert state.reason is not None and "replacement" in state.reason


def test_terminal_blockers_quiet_while_in_flight(
    tmp_home: Path, tmp_path: Path
) -> None:
    from sase.core.wait_dependency_resolution._types import ArtifactCandidate
    from sase.scripts._chop_wait_checks_terminal import terminal_blockers

    old = tmp_path / "old" / "20261009T120000"
    _write_failed_row(old, pending=True)
    candidate = ArtifactCandidate(
        name="pinned",
        timestamp="20261009T120000",
        project_name="sase",
        artifact_dir=str(old),
        parent_timestamp=None,
        agent_session_name=None,
        is_resolved=False,
        is_done=True,
        is_identity_success=False,
        outcome="failed",
        has_done_marker=True,
    )
    index = SimpleNamespace(
        terminal_blocking_artifacts_for_name=lambda *a, **k: (candidate,),
        terminal_blocking_artifacts_for_hood=lambda *a, **k: (),
    )
    blockers = terminal_blockers(
        index,
        ["pinned"],
        [],
        [],
        ("pinned",),
        self_artifact_dir=Path("/tmp/sase/projects/sase/artifacts/ace-run/9"),
    )
    assert blockers == ()

    done = json.loads((old / "done.json").read_text(encoding="utf-8"))
    done["recovery"]["state"] = "declined"
    (old / "done.json").write_text(json.dumps(done), encoding="utf-8")
    blockers = terminal_blockers(
        index,
        ["pinned"],
        [],
        [],
        ("pinned",),
        self_artifact_dir=Path("/tmp/sase/projects/sase/artifacts/ace-run/9"),
    )
    assert len(blockers) == 1
    assert blockers[0].outcome == "failed"


def test_forward_identity_deps(
    tmp_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_wait_deps import _forward_identity_deps

    old = tmp_path / "old" / "20261009T120000"
    new = tmp_path / "new" / "20261009T130000"
    _write_failed_row(old)
    new.mkdir(parents=True)
    _fake_launched_record(monkeypatch, old, new)
    shutil.rmtree(old)

    deps = [{"artifact_dir": str(old), "name": "pinned"}]
    mapped = _forward_identity_deps(deps)
    assert mapped == [{"artifact_dir": str(new), "name": "pinned"}]
    assert deps == [{"artifact_dir": str(old), "name": "pinned"}]
