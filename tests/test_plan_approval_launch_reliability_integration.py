"""Combined approval-to-launch lifecycle regressions for sase-s2.

These tests stitch the host-owned plan archive (sase-s2.1) and the
swap-safe epic launcher (sase-s2.2) into one journey each, and they
reproduce the historical two-writer / fail-fast failures that those
fixes replaced.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_successor import SuccessorRequest
from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.dev_update.code_swap_lock import (
    code_swap_writer_lock,
    guarded_exec_argv,
)
from sase.history.chat import save_chat_history
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.poller import poll_gate, wait_for_gate
from sase.plan_gate import (
    create_plan_approval_gate,
    translate_plan_gate_response,
)
from sase.sdd._artifact_link_commit import (
    ARTIFACT_LINK_COMMIT_MESSAGE,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state
from tests._plan_gate_fixtures import (  # noqa: F401
    plan_gate_home,
    write_plan,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo
from tests.test_bead.cli_work_from_plan_helpers import (
    EPIC_PLAN,
    write_plan_update,
)
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution
from tests.workspace_lease_helpers import fake_operational_lease

_MONTH = "202608"
_PLAN_STEM = "family_shell_metadata"
_HOST_CREATE_TIME = "2026-08-22 11:33:24"
_RUNNER_CREATE_TIME = "2026-08-22 11:33:26"
_WAITING_NEEDLE = "waiting for the source-tree swap to finish"


def _archived_tale(create_time: str) -> str:
    return (
        "---\n"
        "tier: tale\n"
        "title: Approved implementation\n"
        "goal: Deliver the approved implementation\n"
        "size: small\n"
        f"create_time: {create_time}\n"
        "status: wip\n"
        "---\n"
        "# Plan\n"
        "\n"
        "Implement the requested change.\n"
    )


def _plans_sidecar(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "plans.git"
    init_bare_repo(origin)
    seed = tmp_path / "plans-seed"
    clone(origin, seed)
    (seed / "README.md").write_text("plans\n", encoding="utf-8")
    commit_all(seed, "init plans")
    git(["push", "-u", "origin", "main"], seed)
    host = tmp_path / "host-plans"
    runner = tmp_path / "runner-plans"
    clone(origin, host)
    clone(origin, runner)
    return origin, host, runner


def _git(args: list[str], cwd: Path) -> str:
    return git(args, cwd).stdout.strip()


def _log_subjects(repo: Path) -> list[str]:
    log = _git(["log", "--pretty=%s", "HEAD"], repo)
    return [line for line in log.splitlines() if line]


def _assert_linear_history(repo: Path) -> None:
    rows = _git(["rev-list", "--parents", "HEAD"], repo).splitlines()
    assert rows
    for row in rows:
        parts = row.split()
        assert len(parts) <= 2, f"merge commit in {repo}: {row}"


def _link_row(plan_ref: str) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "agent:planner.coder",
        "relation": "read",
        "target_ref": plan_ref,
        "description": "Coder consumed the canonical approved plan",
        "origin": "read",
        "created_by": "planner.coder",
        "created_at": "2026-08-22T11:34:00Z",
        "uses": 1,
    }


def _write_link_index(repo: Path, plan_ref: str) -> Path:
    path = sidecar_index_path(repo, plan_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": plan_ref,
        "rows": [_link_row(plan_ref)],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _commit_link_index(repo: Path, index: Path) -> None:
    result = commit_artifact_link_indexes(
        [index],
        repo_roots=(repo,),
        push_after_commit=False,
        verify_publication=False,
    )
    assert result.committed is True
    git(["push"], repo)


def _dirty_state(repo: Path, changed: tuple[str, ...]) -> DirtyState:
    path = normalize_path(str(repo))
    return DirtyState(
        project_dir=path,
        repos=(
            DirtyRepo(
                name="plans",
                path=path,
                changed_files=changed,
                kind="sdd",
            ),
        ),
        details="",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(),
        details="",
    )


def _rebase_onto_origin(repo: Path) -> subprocess.CompletedProcess[str]:
    git(["fetch", "origin"], repo)
    return subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_two_writer_sidecar_race_blocks_artifact_link_rebase(
    tmp_path: Path,
) -> None:
    """The 0aj chronology: sibling plan commits poison a later link rebase."""
    _origin, host, runner = _plans_sidecar(tmp_path)
    rel = f"{_MONTH}/{_PLAN_STEM}.md"
    plan_ref = f"plan:{rel}"
    host_plan = host / rel
    runner_plan = runner / rel
    host_plan.parent.mkdir(parents=True)
    runner_plan.parent.mkdir(parents=True)
    host_plan.write_text(_archived_tale(_HOST_CREATE_TIME), encoding="utf-8")
    commit_all(host, f"Archive approved plan {_PLAN_STEM}")
    git(["push"], host)
    runner_plan.write_text(_archived_tale(_RUNNER_CREATE_TIME), encoding="utf-8")
    commit_all(runner, f"Add SDD files for {_PLAN_STEM}")
    index = _write_link_index(runner, plan_ref)
    git(["add", str(index.relative_to(runner))], runner)
    git(["commit", "-m", ARTIFACT_LINK_COMMIT_MESSAGE], runner)
    runner_subjects = _log_subjects(runner)
    host_subjects = _log_subjects(host)
    assert f"Add SDD files for {_PLAN_STEM}" in runner_subjects
    assert f"Archive approved plan {_PLAN_STEM}" in host_subjects

    rebase = _rebase_onto_origin(runner)
    try:
        assert rebase.returncode != 0
        conflicted = _git(["diff", "--name-only", "--diff-filter=U"], runner)
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
    origin, host, runner = _plans_sidecar(tmp_path)
    plan_path = write_plan(gate_home, f"{_PLAN_STEM}.md", VALID_TALE_PLAN)
    gate = create_plan_approval_gate(plan_path, f"lifecycle-{start_order}")
    saved = host / _MONTH / f"{_PLAN_STEM}.md"
    archived = _archived_tale(_HOST_CREATE_TIME)
    plan_ref = f"plan:{_MONTH}/{_PLAN_STEM}.md"
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
        commit_all(host, f"Archive approved plan {_PLAN_STEM}")
        git(["push"], host)
        return _ApprovedPlanArchive(saved, plan_ref)

    def wait_then_result(*_args: object, **_kwargs: object) -> PlanApprovalResult:
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
                "sase.llm_provider._plan_utils.handle_plan_approval",
                side_effect=wait_then_result,
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
            patch("sase.axe.run_agent_exec_plan.was_killed", return_value=False)
        )
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
        stack.enter_context(patch("sase.sdd.files.get_yyyymm", return_value=_MONTH))
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
            if start_order == "poller_first":
                runner_future = pool.submit(runner_resume)
                assert runner_started.wait(timeout=5)
                assert poller_waiting.wait(timeout=5)
                host_future = pool.submit(host_approve)
                assert archive_started.wait(timeout=5)
            else:
                host_future = pool.submit(host_approve)
                assert archive_started.wait(timeout=5)
                runner_future = pool.submit(runner_resume)
                assert runner_started.wait(timeout=5)
            assert not gate.response_path.exists()
            assert poll_gate(gate.bundle_path) is None
            assert writes == []
            release.set()
            execution = host_future.result(timeout=10)
            outcome = runner_future.result(timeout=10)

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
    runner_plan = runner / _MONTH / f"{_PLAN_STEM}.md"
    assert saved.read_text(encoding="utf-8") == archived
    assert runner_plan.read_text(encoding="utf-8") == archived
    saved_text = saved.read_text(encoding="utf-8")
    host_front, _host_body, _ = parse_frontmatter(saved_text)
    assert f"create_time: {_HOST_CREATE_TIME}" in saved_text
    assert host_front["status"] == "wip"
    assert _log_subjects(host) == [
        f"Archive approved plan {_PLAN_STEM}",
        "init plans",
    ]
    _assert_linear_history(host)

    index = _write_link_index(host, plan_ref)
    before = _dirty_state(runner, (f"links/{_MONTH}/{_PLAN_STEM}.md.json",))
    fingerprint = progress_fingerprint(before)
    _commit_link_index(host, index)
    rebase = _rebase_onto_origin(runner)
    assert rebase.returncode == 0, rebase.stderr
    git(["reset", "--hard", "origin/main"], runner)
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(runner),
        fingerprint_before=fingerprint,
    )
    assert evidence == ()
    assert ARTIFACT_LINK_COMMIT_MESSAGE in _log_subjects(host)
    assert f"Add SDD files for {_PLAN_STEM}" not in _log_subjects(host)
    assert f"Add SDD files for {_PLAN_STEM}" not in _log_subjects(runner)
    _assert_linear_history(origin)
    _assert_linear_history(host)
    _assert_linear_history(runner)
    assert (runner / f"links/{_MONTH}/{_PLAN_STEM}.md.json").is_file()

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
    gate = create_plan_approval_gate(
        write_plan(gate_home, f"order-{start_order}.md", VALID_TALE_PLAN),
        f"order-{start_order}",
    )
    started = Event()
    poller_waiting = Event()
    release = Event()
    saved = gate_home / "sdd" / "plans" / _MONTH / "order.md"

    def archive(*_args: object, required: bool = False, **_kwargs: object) -> str:
        assert required is True
        started.set()
        assert not gate.response_path.exists()
        assert poll_gate(gate.bundle_path) is None
        assert release.wait(timeout=5)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(VALID_TALE_PLAN, encoding="utf-8")
        return _ApprovedPlanArchive(saved, f"plan:{_MONTH}/order.md")

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
            if start_order == "poller_first":
                poll_future = pool.submit(poll)
                assert poller_waiting.wait(timeout=5)
                host_future = pool.submit(approve)
                assert started.wait(timeout=5)
            else:
                host_future = pool.submit(approve)
                assert started.wait(timeout=5)
                poll_future = pool.submit(poll)
            assert not gate.response_path.exists()
            release.set()
            host_future.result(timeout=5)
            polled = poll_future.result(timeout=5)

    assert polled.status == "responded"
    result = polled.payload["option_results"][0]["result"]
    assert result["saved_plan_path"] == str(saved)
    assert result["plan_archive_protocol"] == "host_v2"
    assert result["plan_archive_ref"] == f"plan:{_MONTH}/order.md"


def _readline_until(
    proc: subprocess.Popen[str], needle: str, *, timeout: float
) -> str | None:
    stream = proc.stdout
    if stream is None:
        return None
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], max(0.0, remaining))
        if not ready:
            continue
        chunk = stream.readline()
        if chunk == "":
            return None
        buf += chunk
        if needle in buf:
            return buf
    return None


def _install_fake_sase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    marker = tmp_path / "created.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sase = fake_bin / "sase"
    fake_sase.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                f"path = pathlib.Path({str(marker)!r})",
                "path.write_text(json.dumps(sys.argv))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_sase.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    return marker


def _create_one_epic_dag(plan: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    result = work_from_plan_file(
        str(plan),
        dry_run=False,
        yes=True,
        no_push=True,
        render=False,
    )
    assert result.epic_id is not None
    assert launches == [result.epic_id]
    return result.epic_id


@pytest.mark.parametrize("start_order", ["writer_first", "launch_first"])
def test_epic_approval_during_code_swap_creates_one_dag(
    tmp_path: Path,
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_order: str,
) -> None:
    checkout = tmp_path / "bead-project"
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout)
    plan = checkout / "incoming" / "rollout.md"
    plan.parent.mkdir()
    plan.write_text(EPIC_PLAN, encoding="utf-8")
    gate_plan = write_plan(gate_home, "rollout.md", VALID_EPIC_PLAN)
    gate = create_plan_approval_gate(gate_plan, f"epic-{start_order}")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    write_agent_meta_atomic(
        artifacts,
        {"name": "planner", "agent_family": "planner", "status": "running"},
        index_updater=lambda _path: None,
    )
    marker = _install_fake_sase(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}
    lease = fake_operational_lease(
        tmp_path / "leased",
        primary_checkout=checkout,
    )

    def fake_start_monitor(request: object) -> object:
        captured["request"] = request
        proc = subprocess.Popen(
            list(request.execution_argv),  # type: ignore[attr-defined]
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        captured["proc"] = proc
        return SimpleNamespace(
            monitor_id="m7k2xyz",
            monitor_state="running",
            command=request.command,  # type: ignore[attr-defined]
        )

    def prepare_launch(*_args: object, **_kwargs: object) -> object:
        return start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "planner"},
            artifacts_dir=artifacts,
        )

    patches = ExitStack()
    patches.enter_context(
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks")
    )
    patches.enter_context(patch("sase.procs.read_procs", return_value=[]))
    patches.enter_context(
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        )
    )
    patches.enter_context(
        patch("sase.workspace_provider.lease.release_operational_lease")
    )
    patches.enter_context(
        patch("sase.monitor.start.start_monitor", side_effect=fake_start_monitor)
    )
    patches.enter_context(
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=prepare_launch,
        )
    )

    def approve() -> object:
        return execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"epic_launch_mode": "launch"},
        )

    with patches:
        if start_order == "writer_first":
            with code_swap_writer_lock() as writer:
                assert writer.acquired is True
                execution = approve()
                proc = captured["proc"]
                assert isinstance(proc, subprocess.Popen)
                try:
                    line = _readline_until(proc, _WAITING_NEEDLE, timeout=5.0)
                    assert line is not None
                    assert proc.poll() is None
                    assert not marker.exists()
                    assert gate.response_path.exists()
                    with BeadProject(checkout) as project:
                        assert project.list_issues() == []
                except BaseException:
                    proc.kill()
                    proc.wait(timeout=5)
                    raise
            assert proc.wait(timeout=10) == 0
        else:
            execution = approve()
            proc = captured["proc"]
            assert isinstance(proc, subprocess.Popen)
            assert proc.wait(timeout=10) == 0
            assert gate.response_path.exists()

    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload[1:4] == ["bead", "work", str(plan)]
    request = captured["request"]
    logical = build_epic_launch_argv(plan, artifacts_dir=artifacts)
    assert list(request.execution_argv) == guarded_exec_argv(  # type: ignore[attr-defined]
        logical
    )
    assert execution.response["kind"] == "epic_plan"
    epic_id = _create_one_epic_dag(plan, monkeypatch)
    with BeadProject(checkout) as project:
        epic = project.show(epic_id)
        children = project.get_epic_children(epic.id)
        assert epic.tier is BeadTier.EPIC
        assert len(children) == 3
        assert all(issue.issue_type is IssueType.PHASE for issue in children)
        assert len(project.list_issues()) == 4
