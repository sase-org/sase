"""Public chop-author SDK and builtin registry coverage."""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path

import pytest

import sase.chops.builtin as builtin_registry
from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops import ChopReport, Tone
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


def test_report_builder_round_trips_every_block_kind(tmp_path: Path) -> None:
    tone: Tone = "warn"
    report = (
        ChopReport(title=" CI   WATCH ")
        .headline("4 green · 1 red", tone=tone)
        .heading("REPOSITORIES")
        .text("One repository needs attention.", tone="info")
        .kv({"mode": "dry run"}, tone="muted")
    )
    rows = report.rows(columns=("REPOSITORY", "STATE", "EVIDENCE"))
    rows.row(("sase-org/sase", "red", "ci / test"), tone="error", glyph="▲")
    rows.row(("sase-org/sase-core", "green", "a1b2c3d"), tone="ok")
    report.bullets(("Inspect the failure", "Propose a fix"), tone="info", glyph="•")
    report.gauge("passing repositories", 4, 5, tone="warn").divider()

    report_document = report.to_dict()
    assert report_document["title"] == "CI WATCH"
    assert [block["kind"] for block in report_document["blocks"]] == [
        "headline",
        "heading",
        "text",
        "kv",
        "rows",
        "bullets",
        "gauge",
        "divider",
    ]
    assert report_document["blocks"][3]["items"] == [
        {"key": "mode", "value": "dry run", "tone": "muted"}
    ]
    assert report_document["blocks"][4]["rows"][0] == {
        "cells": ["sase-org/sase", "red", "ci / test"],
        "tone": "error",
        "glyph": "▲",
    }

    result_path = tmp_path / "report.json"
    document = ChopResultBuilder(summary="ci_watch: repos=5", report=report).write(
        result_path
    )
    assert [block["kind"] for block in document["report"]["blocks"]] == [
        "headline",
        "heading",
        "text",
        "kv",
        "rows",
        "bullets",
        "gauge",
        "divider",
    ]
    assert json.loads(result_path.read_text(encoding="utf-8")) == document


def test_report_builder_validates_tones_and_glyphs() -> None:
    report = ChopReport()

    with pytest.raises(ValueError, match="unknown chop report tone"):
        report.headline("finding", tone="rainbow")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="allowlisted"):
        report.bullets(("finding",), glyph="🚨")
    with pytest.raises(ValueError, match="allowlisted"):
        report.rows().row(("finding",), glyph="x")


def test_report_builder_normalizes_and_truncates_strings() -> None:
    report = ChopReport(title="  TITLE\tWITH\nSPACE  " + "x" * 80)
    report.headline(" left\tmiddle\nright\0 " + "x" * 600)
    report.kv({" \n ": "ignored", " mode ": " dry\t run "})
    report.bullets(("", "\0", " useful\nitem "))

    document = report.to_dict()
    assert document["title"] == "TITLE WITH SPACE " + "x" * 46 + "…"
    assert len(document["title"]) == 64
    headline = document["blocks"][0]["text"]
    assert headline.startswith("left middle right ")
    assert headline.endswith("…")
    assert len(headline) == 512
    assert document["blocks"][1]["items"] == [{"key": "mode", "value": "dry run"}]
    assert document["blocks"][2]["items"] == [{"text": "useful item"}]
    assert headline.isprintable()


def test_report_rows_reject_mismatched_cell_counts() -> None:
    rows = ChopReport().rows(columns=("NAME", "STATE"))

    with pytest.raises(ValueError, match="row has 1 cells, expected 2"):
        rows.row(("only-one",))


def test_empty_report_blocks_are_dropped() -> None:
    report = ChopReport(title="\n")
    report.headline("\0").heading("  ").text("\t").kv({"": ""}).bullets(("",))
    report.rows(columns=("NAME",))

    assert report.to_dict() == {"blocks": []}
    assert ChopResultBuilder(report=report).to_dict() == {
        "schema_version": 1,
        "status": "ok",
        "counters": {},
        "proposed_launches": [],
    }


def test_result_without_report_keeps_existing_document_shape() -> None:
    assert ChopResultBuilder(
        status="no_op",
        summary="audit: findings=0 reason=no_findings",
        reason="no_findings",
        counters={"findings": 0},
        evidence=["audit.json"],
        proposed_launches=[
            {"prompt": "Audit.", "workspace": "git:sase"},
        ],
    ).to_dict() == {
        "schema_version": 1,
        "status": "no_op",
        "counters": {"findings": 0},
        "proposed_launches": [
            {"prompt": "Audit.", "workspace": "git:sase"},
        ],
        "summary": "audit: findings=0 reason=no_findings",
        "reason": "no_findings",
        "evidence": ["audit.json"],
    }


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
