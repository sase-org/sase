"""Agent Hijack canary scenarios and their TUI ingress fakes."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agent_durable import submit_agent_hijack
from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.actions.agents._hijack_decision import compute_hijack_decision
from sase.ace.tui.models import Agent
from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.hijack.ledger import (
    find_active_record_by_target_key,
    load_record,
    load_record_by_artifacts_dir,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.names import AGENT_PERSIST_HIJACK
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.running_field import get_claimed_workspaces
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.fakey.harness import FakeyBarrier, _wait_for_condition
from tests.fakey._agent_hijack_canary_harness import CanaryHarness
from tests.fakey._agent_hijack_canary_harness import _finalizer_complete_path
from tests.fakey._agent_hijack_canary_support import (
    SESSION,
    WORKSPACE_NUM,
    read_json,
)


def _prompt(*, directive: str, body: str, barrier: FakeyBarrier | None) -> str:
    header = f"{directive.rstrip()}\n" if directive.strip() else ""
    if barrier is None:
        scenario = "reply: canary settled\n"
    else:
        scenario = yaml.safe_dump(
            {
                "steps": barrier.steps(),
                "reply": "canary recovered",
            },
            sort_keys=False,
        )
    return f"{header}%model:fakey-large\n{body}\n\n```fakey\n{scenario.rstrip()}\n```\n"


class _HijackHost(AgentHijackActionMixin):
    """TUI hijack ingress that runs persist-hijack on the calling thread."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self._monkeypatch = monkeypatch
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self.notifications: list[tuple[str, str]] = []
        self.current_idx = 0
        self.last_payload: dict[str, Any] | None = None

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail

    def _submit_durable_proc(self, argv: Any, **kwargs: Any) -> SimpleNamespace:
        del argv
        request_path = self.root / "persist-hijack-request.json"
        result_path = self.root / "persist-hijack-result.json"
        payload = dict(kwargs["request"])
        write_operation_request(
            request_path,
            DurableOperationRequest(
                operation=str(kwargs["operation"]),
                payload=payload,
            ),
        )
        from sase.main.parser import create_parser
        from sase.ops.commands.agent import handle_agent_operation

        self._monkeypatch.setenv("SASE_PROC_ID", "hijack-canary")
        args = create_parser().parse_args(
            [
                "agent",
                "persist-hijack",
                "-Q",
                str(request_path),
                "-R",
                str(result_path),
            ]
        )
        code = handle_agent_operation(args)
        loaded = read_operation_result(
            result_path,
            expected_operation=AGENT_PERSIST_HIJACK,
            expected_proc_id="hijack-canary",
        )
        self.last_payload = dict(loaded.payload or {})
        on_complete = kwargs.get("on_complete")
        if callable(on_complete):
            on_complete(
                SimpleNamespace(
                    payload=dict(loaded.payload or {}),
                    message=loaded.message,
                    success=loaded.success and code == 0,
                )
            )
        assert loaded.success and code == 0, (
            f"persist-hijack failed: code={code} message={loaded.message!r} "
            f"error={loaded.error!r} payload={loaded.payload!r}"
        )
        return SimpleNamespace(proc_id="hijack-canary")


def _hijack(
    harness: CanaryHarness, name: str, row: Agent, *, tui_row: Agent | None = None
) -> dict[str, Any]:
    decision = compute_hijack_decision(row)
    assert decision.mode == "immediate", (
        f"expected immediate hijack, got {decision.decision!r}"
    )
    host = _HijackHost(harness.root, harness.monkeypatch)
    rows = harness.load_rows()
    host._agents = rows
    host._agents_with_children = rows
    target = tui_row or row
    host._store_hijack_decision(target, decision)
    if name != (decision.occupant_name or target.agent_name):
        submitted = submit_agent_hijack(
            host,
            name=name,
            identity=str(target.identity),
            cl_name=target.cl_name,
            project_file=target.project_file or str(harness.project_file),
            display_name=f"Hijack {name}",
            session_name=name,
        )
        assert submitted, f"TUI persist-hijack did not submit: {host.notifications!r}"
    else:
        assert host._start_hijack_agent(target), (
            f"TUI hijack ingress failed: {host.notifications!r} "
            f"decision={decision.decision!r}"
        )
    return decision.decision


def _request_latch(
    harness: CanaryHarness, name: str, row: Agent
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision = compute_hijack_decision(row)
    assert decision.mode == "latched", (
        f"decision={decision.decision!r} row_name={row.agent_name!r} "
        f"workspace={row.workspace_num!r} session={row.agent_session!r} "
        f"status={row.status!r} pid={row.pid!r}"
    )
    host = _HijackHost(harness.root, harness.monkeypatch)
    rows = harness.load_rows()
    host._agents = rows
    host._agents_with_children = rows
    target = next((item for item in rows if item.identity == row.identity), row)
    assert target.agent_name == name, (target.agent_name, name)
    host._store_hijack_decision(target, decision)
    assert host._start_hijack_agent(target), (
        f"TUI latch ingress failed: {host.notifications!r} "
        f"decision={decision.decision!r}"
    )
    assert host.last_payload is not None
    assert host.last_payload.get("status") == "latched", host.last_payload
    return decision.decision, host.last_payload


def _stage_pipe(
    launch: AgentLaunchResult,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> dict[str, Any]:
    from sase.main.pipe_handler import handle_pipe_command

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(launch.artifacts_dir))
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        with pytest.raises(SystemExit) as exit_info:
            handle_pipe_command(prompt, reason="canary staged handoff")
    assert exit_info.value.code == 0
    staged = read_staged_handoff(launch.artifacts_dir)
    assert staged is not None and staged.get("kind") == "pipe", staged
    return staged


def _workspace_successors(
    harness: CanaryHarness, launch: AgentLaunchResult
) -> list[dict[str, Any]]:
    parent = Path(launch.artifacts_dir).resolve()
    successors: list[dict[str, Any]] = []
    for artifacts_dir in iter_agent_artifact_dirs(harness.project, newest_first=False):
        if artifacts_dir.resolve() == parent:
            continue
        meta_path = artifacts_dir / "agent_meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        if int(meta.get("workspace_num") or 0) == WORKSPACE_NUM:
            if meta.get("pid"):
                harness.pids.append(int(meta["pid"]))
            meta["_artifacts_dir"] = str(artifacts_dir)
            successors.append(meta)
    return successors


def test_finalizing_latch_suppresses_staged_pipe_then_continues_same_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_barrier = FakeyBarrier(
        started=tmp_path / "barriers" / "model.started",
        release=tmp_path / "barriers" / "model.release",
        timeout=LOAD_TOLERANT_TIMEOUT,
    )
    finalizer_barrier = FakeyBarrier(
        started=tmp_path / "barriers" / "finalizer.started",
        release=tmp_path / "barriers" / "finalizer.release",
        timeout=LOAD_TOLERANT_TIMEOUT,
    )
    harness = CanaryHarness(tmp_path, monkeypatch, finalizer_barrier=finalizer_barrier)
    launch: AgentLaunchResult | None = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="",
                body="Hold while the canary stages a handoff.",
                barrier=model_barrier,
            )
        )
        meta = harness.wait_meta(launch)
        agent_name = str(meta["name"])
        harness.wait_barrier(launch, model_barrier)
        staged = _stage_pipe(
            launch,
            monkeypatch,
            "SUPPRESSED PIPE PAYLOAD: preserve this text for recovery only.",
        )

        model_barrier.open()
        finalizer_barrier.wait_until_started()
        row = harness.row_for_launch(launch)
        decision, request = _request_latch(harness, agent_name, row)
        hijack_id = str(request["hijack_id"])
        initial_record = load_record(hijack_id)
        assert initial_record is not None, request
        target_key = str(initial_record["target_key"])
        record = find_active_record_by_target_key(target_key)
        assert record is not None and record["hijack_id"] == hijack_id
        assert record["state"] == "latched", record
        assert not (Path(launch.artifacts_dir) / "done.json").exists()
        claims_before_finalizer = get_claimed_workspaces(str(harness.project_file))
        assert any(
            claim.workspace_num == WORKSPACE_NUM
            and claim.pid == int(meta["pid"])
            and claim.artifacts_timestamp == Path(launch.artifacts_dir).name
            for claim in claims_before_finalizer
        ), claims_before_finalizer
        assert _workspace_successors(harness, launch) == []

        finalizer_barrier.open()
        done = harness.wait_done(launch)
        assert done.get("outcome") == "hijacked", done
        assert (
            _finalizer_complete_path(finalizer_barrier).read_text(encoding="utf-8")
            == "finalized\n"
        )
        finalizer_result = read_json(
            Path(launch.artifacts_dir) / "finalizer_result.json"
        )
        assert finalizer_result["status"] == "success", finalizer_result

        hijacked = harness.wait_status(launch, "HIJACKED")
        _wait_for_condition(
            lambda: (
                (applied := load_record(hijack_id)) is not None
                and applied["state"] == "held"
            ),
            LOAD_TOLERANT_TIMEOUT,
            f"hijack latch {hijack_id} to finish evidence publication",
        )
        held = load_record(hijack_id)
        assert held is not None and held["state"] == "held", {
            "record": held,
            "meta": meta,
            "claims": get_claimed_workspaces(str(harness.project_file)),
            "project_file": Path(harness.project_file).read_text(encoding="utf-8"),
            "claim_ledger": read_ledger_records(
                project_file=str(harness.project_file), workspace_num=WORKSPACE_NUM
            ),
        }
        assert held["boundary"] == "staged_adoption", held
        assert held["suppressed_followup"] == {
            "kind": "pipe",
            "ref": str(Path(launch.artifacts_dir) / STAGED_HANDOFF_FILENAME),
        }
        staged_path = Path(str(held["suppressed_followup"]["ref"]))
        retained = read_json(staged_path)
        assert retained["staged_id"] == staged["staged_id"]
        assert retained["payload"]["prompt"] == (
            "SUPPRESSED PIPE PAYLOAD: preserve this text for recovery only."
        )
        claim = _pinned_claim(harness)
        assert claim.pinned or "PINNED" in claim.suffix_fields
        assert hijacked.workspace_num == WORKSPACE_NUM
        assert _workspace_successors(harness, launch) == []

        model_barrier.open()
        code = _recover_continue(harness, agent_name)
        assert code == 0, (
            f"recover continue failed: {harness.last_recover!r}\n"
            + harness.diagnostics(launch)
        )

        _wait_for_condition(
            lambda: any(
                (Path(str(meta["_artifacts_dir"])) / "done.json").is_file()
                for meta in _workspace_successors(harness, launch)
            ),
            LOAD_TOLERANT_TIMEOUT,
            "recovery successor to settle in the retained workspace",
        )
        continued = harness.wait_status(launch, "CONTINUED")
        assert continued.workspace_num == WORKSPACE_NUM
        successors = _workspace_successors(harness, launch)
        assert len(successors) == 1, successors
        assert successors[0].get("name") != agent_name
        resolved = load_record(hijack_id)
        assert resolved is not None and resolved["state"] == "resolved", resolved
        assert resolved["suppressed_followup"] == held["suppressed_followup"]
        assert decision["mode"] == "latched"
    finally:
        model_barrier.open()
        finalizer_barrier.open()
        harness.close()


def test_finalizing_latch_without_handoff_moots_and_keeps_real_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_barrier = FakeyBarrier(
        started=tmp_path / "barriers" / "moot-model.started",
        release=tmp_path / "barriers" / "moot-model.release",
        timeout=LOAD_TOLERANT_TIMEOUT,
    )
    finalizer_barrier = FakeyBarrier(
        started=tmp_path / "barriers" / "moot-finalizer.started",
        release=tmp_path / "barriers" / "moot-finalizer.release",
        timeout=LOAD_TOLERANT_TIMEOUT,
    )
    harness = CanaryHarness(tmp_path, monkeypatch, finalizer_barrier=finalizer_barrier)
    launch: AgentLaunchResult | None = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="%id:canary",
                body="Finish normally after the canary requests a latch.",
                barrier=model_barrier,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": SESSION},
        )
        meta = harness.wait_meta(launch)
        agent_name = str(meta["name"])
        harness.wait_barrier(launch, model_barrier)
        model_barrier.open()
        finalizer_barrier.wait_until_started()

        row = harness.row_for_launch(launch)
        _, request = _request_latch(harness, agent_name, row)
        hijack_id = str(request["hijack_id"])
        initial_record = load_record(hijack_id)
        assert initial_record is not None, request
        target_key = str(initial_record["target_key"])
        finalizer_barrier.open()

        done = harness.wait_done(launch)
        assert done.get("outcome") in {"success", "completed"}, done
        assert (
            _finalizer_complete_path(finalizer_barrier).read_text(encoding="utf-8")
            == "finalized\n"
        )
        finalizer_result = read_json(
            Path(launch.artifacts_dir) / "finalizer_result.json"
        )
        assert finalizer_result["status"] == "success", finalizer_result

        record = load_record(hijack_id)
        assert record is not None and record["state"] == "finished_first", record
        assert record["boundary_outcome"] == done["outcome"], record
        assert find_active_record_by_target_key(target_key) is None
        claims = get_claimed_workspaces(str(harness.project_file))
        assert not any(
            claim.workspace_num == WORKSPACE_NUM
            and (claim.pinned or "PINNED" in claim.suffix_fields)
            for claim in claims
        ), claims
        assert _workspace_successors(harness, launch) == []
    finally:
        model_barrier.open()
        finalizer_barrier.open()
        harness.close()


def _recover_continue(harness: CanaryHarness, name: str) -> int:
    from sase.agents.cli_recover import handle_agents_recover
    from sase.main.parser import create_parser

    args = create_parser().parse_args(
        [
            "agent",
            "recover",
            "-a",
            "continue",
            "-m",
            "fakey/fakey-large",
            "-j",
            name,
        ]
    )
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = handle_agents_recover(args)
    harness.last_recover = (code, stdout.getvalue(), stderr.getvalue())
    return code


def _pinned_claim(harness: CanaryHarness) -> Any:
    claims = get_claimed_workspaces(str(harness.project_file))
    numbered = [claim for claim in claims if claim.workspace_num == WORKSPACE_NUM]
    assert numbered, f"no claim for workspace #{WORKSPACE_NUM}: {claims!r}"
    return numbered[0]


def _dirty_workspace(workspace: Path) -> None:
    (workspace / "canary-work.txt").write_text("held work\n", encoding="utf-8")


def test_anonymous_tmp_workflow_hijack_continue_same_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CanaryHarness(tmp_path, monkeypatch)
    barrier = harness.barrier("anon")
    launch: AgentLaunchResult | None = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="",
                body="Hold until the canary hijacks this anonymous turn.",
                barrier=barrier,
            )
        )
        meta = harness.wait_meta(launch)
        agent_name = str(meta["name"])
        assert agent_name
        harness.wait_barrier(launch, barrier)
        row = harness.row_for_launch(launch)
        assert row.status in {"RUNNING", "STARTING", "RETRYING"}, (
            harness._row_summaries()
        )
        assert row.workspace_num == WORKSPACE_NUM
        _dirty_workspace(harness.workspace)
        _hijack(harness, agent_name, row)
        done = harness.wait_done(launch)
        assert done.get("outcome") == "hijacked", done

        hijacked = harness.wait_status(launch, "HIJACKED")
        claim = _pinned_claim(harness)
        assert claim.pinned or "PINNED" in claim.suffix_fields
        record = None
        if hijacked.hijack_id:
            record = load_record(str(hijacked.hijack_id))
        if record is None:
            record = load_record_by_artifacts_dir(str(launch.artifacts_dir))
        assert record is not None
        snapshots = record.get("snapshots")
        assert isinstance(snapshots, list) and snapshots, record

        barrier.open()
        code = _recover_continue(harness, agent_name)
        assert code == 0, (
            f"recover continue failed: {harness.last_recover!r}\n"
            + harness.diagnostics(launch)
        )

        def successor_settled() -> bool:
            for artifacts_dir in iter_agent_artifact_dirs(
                harness.project, newest_first=False
            ):
                meta_path = artifacts_dir / "agent_meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    child = read_json(meta_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if child.get("name") == agent_name:
                    continue
                if int(child.get("workspace_num") or 0) != WORKSPACE_NUM:
                    continue
                if child.get("pid"):
                    harness.pids.append(int(child["pid"]))
                done = artifacts_dir / "done.json"
                if not done.is_file():
                    continue
                try:
                    payload = read_json(done)
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("outcome") in {"success", "hijacked", "completed"}:
                    return True
            return False

        _wait_for_condition(
            successor_settled,
            LOAD_TOLERANT_TIMEOUT,
            "recovery successor to settle in the same workspace",
        )
        continued = harness.wait_status(launch, "CONTINUED")
        assert continued.workspace_num == WORKSPACE_NUM
    finally:
        barrier.open()
        harness.close()


def test_session_hijack_chooses_running_member_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CanaryHarness(tmp_path, monkeypatch)
    barrier = harness.barrier("member")
    parent: AgentLaunchResult | None = None
    child: AgentLaunchResult | None = None
    try:
        parent = harness.spawn(
            _prompt(
                directive="%id:canary",
                body="Finish so member --1 can take the workspace.",
                barrier=None,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": SESSION},
        )
        parent_done = harness.wait_done(parent)
        assert parent_done.get("outcome") in {"success", "completed"}, (
            harness.diagnostics(parent)
        )
        harness.wait_workspace_released()

        child = harness.spawn(
            _prompt(
                directive="%id(1, session=canary)",
                body="Hold the session claim until hijacked.",
                barrier=barrier,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": f"{SESSION}--1"},
        )
        child_meta = harness.wait_meta(child)
        member_name = str(child_meta["name"])
        assert member_name.endswith("--1"), child_meta
        harness.wait_barrier(child, barrier)
        member_row = harness.row_for_launch(child)
        assert member_row.status in {"RUNNING", "STARTING", "RETRYING"}, (
            harness._row_summaries()
        )

        subject, decision = resolve_and_decide(SESSION)
        assert subject.occupant_name == member_name, (
            f"resolver occupant={subject.occupant_name!r} reason={subject.occupant_reason!r} "
            f"decision={decision!r}"
        )
        assert decision.get("mode") == "immediate", decision

        session_row = member_row
        for row in harness.load_rows():
            if row.agent_name == SESSION or (
                getattr(row, "is_agent_session_container_row", False)
                and getattr(row, "agent_session", None) == SESSION
            ):
                session_row = row
                break
        _dirty_workspace(harness.workspace)
        _hijack(harness, SESSION, session_row)
        harness.wait_status(child, "HIJACKED")
        claim = _pinned_claim(harness)
        assert claim.pinned or "PINNED" in claim.suffix_fields
    finally:
        barrier.open()
        harness.close()
