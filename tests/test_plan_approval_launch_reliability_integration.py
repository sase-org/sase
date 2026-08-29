"""Combined approval-to-launch lifecycle regressions for sase-s2.

These tests stitch the host-owned plan archive (sase-s2.1) into one journey
each, and they reproduce the historical two-writer / fail-fast failures that
those fixes replaced. The swap-safe epic launcher (sase-s2.2) journey lives
in test_plan_approval_launch_reliability_epic_launch.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_successor import SuccessorRequest
from sase.history.chat import save_chat_history
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.llm_provider.commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.poller import poll_gate, wait_for_gate
from sase.notification_gates.service import create_gate
from sase.plan_gate import (
    build_plan_approval_gate_spec,
    translate_plan_gate_response,
)
from sase.sdd._artifact_link_commit import ARTIFACT_LINK_COMMIT_MESSAGE
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patch_plan_gate_shell_result,
)
from tests._plan_gate_fixtures import (  # noqa: F401
    plan_gate_home,
    wait_for_archive_start,
    write_plan,
)
from tests.plan_approval_launch_reliability_test_helpers import (
    HOST_CREATE_TIME,
    MONTH,
    PLAN_STEM,
    RUNNER_CREATE_TIME,
    archived_tale,
    assert_linear_history,
    clean_state,
    commit_link_index,
    dirty_state,
    git_output,
    log_subjects,
    plans_sidecar,
    rebase_onto_origin,
    write_link_index,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_store._helpers import commit_all, git


def test_two_writer_sidecar_race_blocks_artifact_link_rebase(
    tmp_path: Path,
) -> None:
    """The 0aj chronology: sibling plan commits poison a later link rebase."""
    _origin, host, runner = plans_sidecar(tmp_path)
    rel = f"{MONTH}/{PLAN_STEM}.md"
    plan_ref = f"plan:{rel}"
    host_plan = host / rel
    runner_plan = runner / rel
    host_plan.parent.mkdir(parents=True)
    runner_plan.parent.mkdir(parents=True)
    host_plan.write_text(archived_tale(HOST_CREATE_TIME), encoding="utf-8")
    commit_all(host, f"Archive approved plan {PLAN_STEM}")
    git(["push"], host)
    runner_plan.write_text(archived_tale(RUNNER_CREATE_TIME), encoding="utf-8")
    commit_all(runner, f"Add SDD files for {PLAN_STEM}")
    index = write_link_index(runner, plan_ref)
    git(["add", str(index.relative_to(runner))], runner)
    git(["commit", "-m", ARTIFACT_LINK_COMMIT_MESSAGE], runner)
    runner_subjects = log_subjects(runner)
    host_subjects = log_subjects(host)
    assert f"Add SDD files for {PLAN_STEM}" in runner_subjects
    assert f"Archive approved plan {PLAN_STEM}" in host_subjects

    rebase = rebase_onto_origin(runner)
    try:
        assert rebase.returncode != 0
        conflicted = git_output(["diff", "--name-only", "--diff-filter=U"], runner)
        combined = f"{rebase.stdout}\n{rebase.stderr}\n{conflicted}"
        assert rel in combined or "conflict" in combined.lower()
    finally:
        subprocess.run(["git", "rebase", "--abort"], cwd=runner, check=False)


@pytest.mark.parametrize("start_order", ["host_first", "poller_first"])
def test_combined_tale_approval_to_coder_link_lifecycle(
    tmp_path: Path,
    gate_home: Path,
    start_order: str,
) -> None:
    origin, host, runner = plans_sidecar(tmp_path)
    plan_path = write_plan(gate_home, f"{PLAN_STEM}.md", VALID_TALE_PLAN)
    gate = create_gate(
        build_plan_approval_gate_spec(plan_path, f"lifecycle-{start_order}")
    )
    saved = host / MONTH / f"{PLAN_STEM}.md"
    archived = archived_tale(HOST_CREATE_TIME)
    plan_ref = f"plan:{MONTH}/{PLAN_STEM}.md"
    archive_started = Event()
    runner_started = Event()
    poller_waiting = Event()
    release = Event()
    writes: list[object] = []
    successors: list[SuccessorRequest] = []
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=runner,
        repo_root=runner,
        remote_url=str(origin),
        sidecar_role="plans",
    )

    def archive(*_args: object, required: bool = False, **_kwargs: object) -> str:
        assert required is True
        archive_started.set()
        assert not gate.response_path.exists()
        assert poll_gate(gate.bundle_path) is None
        assert release.wait(timeout=8)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(archived, encoding="utf-8")
        commit_all(host, f"Archive approved plan {PLAN_STEM}")
        git(["push"], host)
        return _ApprovedPlanArchive(saved, plan_ref)

    def wait_then_result() -> PlanApprovalResult:
        poller_waiting.set()
        polled = wait_for_gate(gate.bundle_path, poll_interval=0.05)
        assert polled.status == "responded"
        translated = translate_plan_gate_response(gate.bundle_path, polled.payload)
        saved_path = translated.get("saved_plan_path")
        assert saved_path == str(saved)
        assert translated.get("plan_archive_protocol") == "host_v2"
        assert translated.get("plan_archive_ref") == plan_ref
        return PlanApprovalResult(
            action="approve",
            plan_file=str(plan_path),
            commit_plan=True,
            run_coder=True,
            saved_plan_path=str(saved_path),
            plan_archive_owner="host",
            plan_archive_state="archived",
            plan_archive_protocol="host_v2",
            plan_archive_ref=plan_ref,
        )

    def refuse_runner_write(*_args: object, **_kwargs: object) -> object:
        writes.append("write_sdd_files")
        raise AssertionError("runner must not write a second canonical plan")

    def refuse_runner_commit(*_args: object, **_kwargs: object) -> object:
        writes.append("commit")
        raise AssertionError("runner must not create Add SDD files")

    def capture_successor(
        _ctx: object,
        _state: object,
        request: SuccessorRequest,
        **_kwargs: object,
    ) -> str:
        successors.append(request)
        return "planner.coder"

    def host_approve() -> object:
        return execute_gate_selection(
            gate.bundle_path,
            ["approve", "commit"],
        )

    def runner_resume() -> str | None:
        runner_started.set()
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        ctx = make_ctx(workspace)
        (workspace / ".git").mkdir(exist_ok=True)
        state = make_state(workspace)
        write_agent_meta_atomic(
            state.current_artifacts_dir,
            {
                "name": "planner",
                "agent_family": "planner",
                "agent_family_role": "root",
                "suffix": ".plan",
                "status": "running",
            },
            index_updater=lambda _path: None,
        )
        result = wait_then_result()
        with patch_plan_gate_shell_result(result):
            return handle_plan_marker({"plan_file": str(plan_path)}, ctx, state)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.plan_approval_actions._archive_plan_for_approval",
                side_effect=archive,
            )
        )
        stack.enter_context(
            patch(
                "sase.sdd.store.materialize_sdd_store",
                return_value=store,
            )
        )
        stack.enter_context(
            patch("sase.sdd.files.write_sdd_files", side_effect=refuse_runner_write)
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files",
                side_effect=refuse_runner_commit,
            )
        )
        stack.enter_context(
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=refuse_runner_commit,
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state",
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan.finalize_handoff_artifacts_as_completed",
            )
        )
        stack.enter_context(patch("sase.axe.run_agent_exec_plan.update_meta_suffix"))
        stack.enter_context(patch("sase.axe.run_agent_exec_plan.reset_killed"))
        stack.enter_context(
            patch("sase.axe.run_agent_exec_plan._write_plan_path_artifact")
        )
        stack.enter_context(
            patch("sase.axe.run_agent_exec_plan.update_step_marker_chat_path")
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan_accept.continue_as_successor",
                side_effect=capture_successor,
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan_accept._publish_planner_prompt_archive",
                return_value=tmp_path / "prompt.md",
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_plan_accept.get_embedded_workflow_refs",
                return_value="",
            )
        )
        stack.enter_context(
            patch(
                "sase.sdd.files.expand_prompt_for_spec",
                side_effect=lambda prompt: prompt,
            )
        )
        stack.enter_context(patch("sase.sdd.files.ensure_bare_git_sdd_initialized"))
        stack.enter_context(patch("sase.sdd.files.get_yyyymm", return_value=MONTH))
        stack.enter_context(
            patch(
                "sase.history.chat_links.format_plan_as_response",
                return_value="approved plan",
            )
        )
        stack.enter_context(
            patch("sase.history.chat_extras.format_extra_sections", return_value="")
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                if start_order == "poller_first":
                    runner_future = pool.submit(runner_resume)
                    assert runner_started.wait(timeout=5)
                    assert poller_waiting.wait(timeout=5)
                    host_future = pool.submit(host_approve)
                    wait_for_archive_start(archive_started, host_future)
                else:
                    host_future = pool.submit(host_approve)
                    wait_for_archive_start(archive_started, host_future)
                    runner_future = pool.submit(runner_resume)
                    assert runner_started.wait(timeout=5)
                assert not gate.response_path.exists()
                assert poll_gate(gate.bundle_path) is None
                assert writes == []
                release.set()
                execution = host_future.result(timeout=10)
                outcome = runner_future.result(timeout=10)
            finally:
                release.set()

    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    primary = response["option_results"][0]["result"]
    assert primary["plan_archive_owner"] == "host"
    assert primary["plan_archive_state"] == "archived"
    assert primary["plan_archive_protocol"] == "host_v2"
    assert primary["plan_archive_ref"] == plan_ref
    assert primary["saved_plan_path"] == str(saved)
    assert execution.response == response
    assert outcome is None
    assert writes == []
    assert len(successors) == 1
    assert successors[0].relationships.get("plan_committed") is True
    assert successors[0].relationships.get("sdd_plan_path") == plan_ref
    assert successors[0].relationships.get("plan_archive_ref") == plan_ref
    assert f"@{plan_ref}" in successors[0].prompt
    assert str(saved) not in successors[0].prompt
    assert str(runner) not in successors[0].prompt

    git(["fetch", "origin"], runner)
    git(["reset", "--hard", "origin/main"], runner)
    runner_plan = runner / MONTH / f"{PLAN_STEM}.md"
    assert saved.read_text(encoding="utf-8") == archived
    assert runner_plan.read_text(encoding="utf-8") == archived
    saved_text = saved.read_text(encoding="utf-8")
    host_front, _host_body, _ = parse_frontmatter(saved_text)
    assert f"create_time: {HOST_CREATE_TIME}" in saved_text
    assert host_front["status"] == "wip"
    assert log_subjects(host) == [
        f"Archive approved plan {PLAN_STEM}",
        "init plans",
    ]
    assert_linear_history(host)

    index = write_link_index(host, plan_ref)
    before = dirty_state(runner, (f"links/{MONTH}/{PLAN_STEM}.md.json",))
    fingerprint = progress_fingerprint(before)
    commit_link_index(host, index)
    rebase = rebase_onto_origin(runner)
    assert rebase.returncode == 0, rebase.stderr
    git(["reset", "--hard", "origin/main"], runner)
    evidence = discarded_dirty_work_evidence(
        before,
        clean_state(runner),
        fingerprint_before=fingerprint,
    )
    assert evidence == ()
    assert ARTIFACT_LINK_COMMIT_MESSAGE in log_subjects(host)
    assert f"Add SDD files for {PLAN_STEM}" not in log_subjects(host)
    assert f"Add SDD files for {PLAN_STEM}" not in log_subjects(runner)
    assert_linear_history(origin)
    assert_linear_history(host)
    assert_linear_history(runner)
    assert (runner / f"links/{MONTH}/{PLAN_STEM}.md.json").is_file()

    planner_artifacts = tmp_path / "workspace" / "artifacts"
    meta_path = planner_artifacts / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "agent_family": "planner",
            "agent_family_role": "code",
            "status": "completed",
            "plan_committed": True,
            "plan_approved": True,
        }
    )
    write_agent_meta_atomic(
        planner_artifacts,
        meta,
        index_updater=lambda _path: None,
    )
    transcript = save_chat_history(
        prompt=f"@{plan_ref}\n\nThe above plan has been reviewed and approved.",
        response="Implemented the approved plan and recorded its artifact link.",
        workflow="ace-run",
        agent="planner.coder",
        timestamp="20260822_113400",
        branch_or_workspace="test",
        metadata_agent="planner.coder",
    )
    stored = json.loads(meta_path.read_text(encoding="utf-8"))
    assert stored["status"] == "completed"
    assert stored["status"] != "failed"
    assert stored["plan_committed"] is True
    chat_path = Path(os.path.expanduser(transcript))
    chat = chat_path.read_text(encoding="utf-8")
    assert "Implemented the approved plan" in chat
    assert "discarded dirty work" not in chat.lower()
    assert "failed" not in chat.lower()


@pytest.mark.parametrize("repeat", range(3))
@pytest.mark.parametrize("start_order", ["host_first", "poller_first"])
def test_archive_publication_order_survives_inverted_scheduling(
    gate_home: Path,
    start_order: str,
    repeat: int,
) -> None:
    del repeat
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, f"order-{start_order}.md", VALID_TALE_PLAN),
            f"order-{start_order}",
        )
    )
    started = Event()
    poller_waiting = Event()
    release = Event()
    saved = gate_home / "sdd" / "plans" / MONTH / "order.md"

    def archive(*_args: object, required: bool = False, **_kwargs: object) -> str:
        assert required is True
        started.set()
        assert not gate.response_path.exists()
        assert poll_gate(gate.bundle_path) is None
        assert release.wait(timeout=5)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(VALID_TALE_PLAN, encoding="utf-8")
        return _ApprovedPlanArchive(saved, f"plan:{MONTH}/order.md")

    def approve() -> object:
        return execute_gate_selection(gate.bundle_path, ["approve", "commit"])

    def poll() -> object:
        poller_waiting.set()
        return wait_for_gate(gate.bundle_path, poll_interval=0.05)

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        side_effect=archive,
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                if start_order == "poller_first":
                    poll_future = pool.submit(poll)
                    assert poller_waiting.wait(timeout=5)
                    host_future = pool.submit(approve)
                    wait_for_archive_start(started, host_future)
                else:
                    host_future = pool.submit(approve)
                    wait_for_archive_start(started, host_future)
                    poll_future = pool.submit(poll)
                assert not gate.response_path.exists()
                release.set()
                host_future.result(timeout=10)
                polled = poll_future.result(timeout=10)
            finally:
                release.set()

    assert polled.status == "responded"
    result = polled.payload["option_results"][0]["result"]
    assert result["saved_plan_path"] == str(saved)
    assert result["plan_archive_protocol"] == "host_v2"
    assert result["plan_archive_ref"] == f"plan:{MONTH}/order.md"
