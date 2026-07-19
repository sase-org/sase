"""Builtin refresh-docs chop coverage."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from sase.axe.chop_proposals import prepare_chop_proposals, proposal_previews
from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops.builtin import run_builtin_chop


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context."""

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def _run_refresh_docs(
    tmp_path: Path,
    *,
    target: dict[str, object] | None,
    vars: dict[str, object] | None = None,
) -> dict[str, object]:
    importlib.import_module("sase.scripts.sase_chop_refresh_docs")
    result_path = tmp_path / "result.json"
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="docs",
            state_dir=str(tmp_path),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
            target=target,
            vars=vars,
        ),
        str(context_path),
    )

    run_builtin_chop("refresh_docs", ["--context", str(context_path)])
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_refresh_docs_emits_chained_update_and_polish_proposals(
    tmp_path: Path,
) -> None:
    result = _run_refresh_docs(
        tmp_path,
        target={
            "name": "sase-core",
            "project": "gh_sase-org__sase-core",
            "workspace": "gh:sase-org/sase-core",
        },
    )

    assert result["status"] == "ok"
    assert result["counters"] == {"proposals": 2, "targets": 1}
    proposals = result["proposed_launches"]
    assert isinstance(proposals, list)
    assert proposals[0]["id"] == "update"
    assert proposals[0]["workspace"] == "gh:sase-org/sase-core"
    assert "Refresh the documentation for sase-core" in proposals[0]["prompt"]
    assert proposals[1]["id"] == "polish"
    assert proposals[1]["wait_on"] == "update"
    assert "Verify every changed description" in proposals[1]["prompt"]

    prepared = prepare_chop_proposals(
        "refresh_docs",
        result,
        target_key="sase-core",
    )
    previews = proposal_previews(prepared)
    assert previews[0]["agent_name"] == "chop.refresh_docs.sase-core.1"
    assert previews[1]["wait_name"] == "chop.refresh_docs.sase-core.1"
    assert "%wait:chop.refresh_docs.sase-core.1" in previews[1]["prompt"]
    assert "#!" not in previews[0]["prompt"]
    assert "#!" not in previews[1]["prompt"]


def test_refresh_docs_accepts_prompt_overrides(tmp_path: Path) -> None:
    result = _run_refresh_docs(
        tmp_path,
        target={"name": "sase", "workspace": "gh:sase-org/sase"},
        vars={
            "prompt": "Write the operator guide.",
            "polish_prompt": "Fact-check the operator guide.",
        },
    )

    proposals = result["proposed_launches"]
    assert isinstance(proposals, list)
    assert [proposal["prompt"] for proposal in proposals] == [
        "Write the operator guide.",
        "Fact-check the operator guide.",
    ]


def test_refresh_docs_fails_closed_without_target_workspace(tmp_path: Path) -> None:
    result = _run_refresh_docs(tmp_path, target={"name": "sase"})

    assert result["status"] == "check_error"
    assert result["reason"] == "missing_target_workspace"
    assert result["proposed_launches"] == []


def test_refresh_docs_fails_closed_for_invalid_prompt_override(
    tmp_path: Path,
) -> None:
    result = _run_refresh_docs(
        tmp_path,
        target={"name": "sase", "workspace": "gh:sase-org/sase"},
        vars={"prompt": ""},
    )

    assert result["status"] == "check_error"
    assert result["reason"] == "invalid_prompt_var"
    assert result["proposed_launches"] == []
