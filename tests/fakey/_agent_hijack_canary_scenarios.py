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
from sase.agent.hijack.ledger import load_record, load_record_by_artifacts_dir
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.names import AGENT_PERSIST_HIJACK
from sase.running_field import get_claimed_workspaces
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.fakey.harness import FakeyBarrier, _wait_for_condition
from tests.fakey._agent_hijack_canary_harness import CanaryHarness
from tests.fakey._agent_hijack_canary_support import (
    PROJECT,
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
            for artifacts_dir in iter_agent_artifact_dirs(PROJECT, newest_first=False):
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
