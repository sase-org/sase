"""Public chop-author SDK and builtin registry coverage."""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path

import pytest

import sase.chops.builtin as builtin_registry
from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops.builtin import (
    BuiltinChopRuntime,
    builtin_chop,
    run_builtin_chop,
)
from sase.chops.sdk import (
    ChopLogger,
    ChopResultBuilder,
    emit_summary,
    launch_proposal,
    parse_chop_arguments,
    parse_summary,
)


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context."""

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def _context(tmp_path: Path, *, result_file: Path) -> Path:
    path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=2,
            max_agent_runners=3,
            zombie_timeout_seconds=120,
            query="status:Ready",
            lumberjack_name="sdk-test",
            state_dir=str(tmp_path),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
            result_file=str(result_file),
        ),
        str(path),
    )
    return path


def test_summary_builder_writes_valid_atomic_result(tmp_path: Path) -> None:
    stdout = io.StringIO()
    logger = ChopLogger(stdout=stdout)
    line = emit_summary(
        "audit",
        {"scanned": 4, "findings": 0, "cursor": "abc123"},
        reason="no_findings",
        logger=logger,
    )
    summary = parse_summary(line)
    assert summary is not None

    result_path = tmp_path / "run" / "result.json"
    document = ChopResultBuilder.from_summary(summary).write(result_path)

    assert stdout.getvalue() == line + "\n"
    assert document["status"] == "no_op"
    assert document["counters"] == {"findings": 0, "scanned": 4}
    assert json.loads(result_path.read_text(encoding="utf-8")) == document
    assert list(result_path.parent.glob("*.tmp")) == []


def test_result_builder_proposal_helper_round_trips(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    clan_summary = "[bold magenta]Finding[/bold magenta]\nSplit with care."
    document = (
        ChopResultBuilder(summary="one finding", counters={"findings": 1})
        .add_evidence("reports/finding.json")
        .propose(
            "Fix the finding.",
            "gh:sase-org/sase",
            proposal_id="fix",
            agent_name="worker",
            clan="findings-@",
            clan_summary=clan_summary,
            model="codex/gpt-5.6-sol",
            env={"FINDING": "1"},
            dedupe_key="finding:1",
        )
        .write(result_path)
    )

    proposal = document["proposed_launches"][0]
    assert proposal["id"] == "fix"
    assert proposal["agent_name"] == "worker"
    assert proposal["clan"] == "findings-@"
    assert proposal["clan_summary"] == clan_summary
    assert proposal["workspace"] == "gh:sase-org/sase"
    assert proposal["env"] == {"FINDING": "1"}
    assert document["evidence"] == ["reports/finding.json"]
    assert json.loads(result_path.read_text(encoding="utf-8")) == document


def test_launch_proposal_omits_absent_clan_summary(tmp_path: Path) -> None:
    legacy = launch_proposal("Audit.", "git:sase", clan="audit", agent_name="one")
    summarized = launch_proposal(
        "Audit.",
        "git:sase",
        clan="audit",
        clan_summary="[bold]Audit clan[/bold]",
        agent_name="one",
    )

    assert "clan_summary" not in legacy
    assert summarized["clan_summary"] == "[bold]Audit clan[/bold]"

    result_path = tmp_path / "legacy.json"
    document = (
        ChopResultBuilder()
        .add_proposal("Audit.", "git:sase", clan="audit", agent_name="one")
        .write(result_path)
    )
    assert "clan_summary" not in document["proposed_launches"][0]
    assert json.loads(result_path.read_text(encoding="utf-8")) == document


def test_common_arguments_and_debug_logging_honor_verbose_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_CHOP_VERBOSE", "1")
    args = parse_chop_arguments(["--context", "context.json"])
    stderr = io.StringIO()
    logger = ChopLogger(verbose=args.verbose, stderr=stderr)
    logger.debug("expanded proposal")

    assert args.verbose is True
    assert stderr.getvalue() == "expanded proposal\n"


def test_builtin_registry_derives_result_from_existing_summary(tmp_path: Path) -> None:
    name = "sdk_registry_test"

    @builtin_chop(name)
    def _run(runtime: BuiltinChopRuntime) -> None:
        runtime.log(f"{name}: inspected=3 changed=0 reason=no_changes")

    result_path = tmp_path / "result.json"
    context_path = _context(tmp_path, result_file=result_path)
    run_builtin_chop(name, ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["counters"] == {"changed": 0, "inspected": 3}
    assert result["reason"] == "no_changes"


def test_hook_builtin_uses_shared_runner_and_emits_noop_result(tmp_path: Path) -> None:
    importlib.import_module("sase.scripts.sase_chop_hook_checks")
    result_path = tmp_path / "result.json"
    context_path = _context(tmp_path, result_file=result_path)
    (tmp_path / "filtered.json").write_text("[]", encoding="utf-8")

    run_builtin_chop("hook_checks", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "no_matching_changespecs"
    assert result["counters"] == {
        "changespecs": 0,
        "hooks": 0,
        "started": 0,
        "updates": 0,
    }


def test_all_builtin_chop_modules_use_the_registry() -> None:
    modules = {
        "comment_checks",
        "comment_zombie_checks",
        "epic_launch_flush",
        "error_digest",
        "hook_checks",
        "managed_tmp_reap",
        "mentor_checks",
        "orphan_cleanup",
        "pending_checks_poll",
        "pr_submitted_checks",
        "refresh_docs",
        "stale_running_cleanup",
        "suffix_transforms",
        "wait_checks",
        "workflow_checks",
    }
    for name in modules:
        importlib.import_module(f"sase.scripts.sase_chop_{name}")

    assert modules <= set(builtin_registry._BUILTIN_CHOPS)
