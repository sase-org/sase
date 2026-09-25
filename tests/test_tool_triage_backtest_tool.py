"""Tests for the read-only `tools/tool_triage_backtest` replay tool."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "tool_triage_backtest"


@pytest.fixture(scope="module")
def backtest() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "tool_triage_backtest", str(TOOL_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_ledger_writes_report_and_audit_without_creating_store(
    tmp_path: Path,
) -> None:
    store = tmp_path / "tools" / "runs.sqlite"
    out_dir = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "--store",
            str(store),
            "--artifacts-root",
            str(tmp_path / "artifacts"),
            "--selection-dir",
            str(tmp_path / "selection"),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    counts = {
        "known_items": 0,
        "known_items_in_runs_with_untracked_paths": 0,
        "known_on_added_or_untracked": 0,
        "selected_runs": 0,
        "workspace_attribution": {"ledger": 0, "agent_meta": 0, "none": 0},
    }
    assert json.loads(completed.stdout) == counts
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["counts"] == counts
    assert report["sample"] == []
    assert (
        (out_dir / "audit.md")
        .read_text(encoding="utf-8")
        .startswith("# Triage backtest audit\n")
    )
    assert not store.exists()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _fixture_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "backtest@example.test")
    _git(repo, "config", "user.name", "Backtest")
    (repo / "Justfile").write_text(
        'check:\n    tools/run_silent "lint (symvision)"\n', encoding="utf-8"
    )
    source = repo / "src" / "sase"
    source.mkdir(parents=True)
    (source / "foo.py").write_text("def helper(): pass\n", encoding="utf-8")
    first = _commit(repo, "first")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    second = _commit(repo, "second")
    return repo, first, second


def _log(path: Path, *, stage: str = "lint (symvision)") -> None:
    path.write_text(
        f"✗ {stage}\nUnused public functions/classes:\n  helper in src/sase/foo.py\n",
        encoding="utf-8",
    )


def _run(
    run_id: str,
    *,
    base: str,
    agent: str,
    created_ts: int,
    settled_ts: int,
    log: Path | None,
    dirty_paths: list[dict[str, str]] | None = None,
    workspace: str | None = None,
) -> dict[str, object]:
    run: dict[str, object] = {
        "run_id": run_id,
        "project": "fixture",
        "tool": "check",
        "agent": agent,
        "created_ts": created_ts,
        "settled_ts": settled_ts,
        "state": "failed",
        "exit_code": 1,
        "fingerprint_before": {
            "schema_version": 1,
            "repos": [
                {
                    "identity": "fixture",
                    "head": base,
                    "dirty_paths": dirty_paths or [],
                }
            ],
            "completeness": {"complete": True},
        },
    }
    if log is not None:
        run["logs"] = {"stdout_path": str(log)}
    if workspace is not None:
        run["workspace"] = workspace
    return run


def _namespace(repo: Path, artifacts: Path, out_dir: Path) -> Namespace:
    return Namespace(
        store="unused.sqlite",
        repo_root=str(repo),
        project="fixture",
        tool="check",
        artifacts_root=str(artifacts),
        selection_dir=str(artifacts / "selection"),
        out_dir=str(out_dir),
        sample=1,
        seed=9,
        min_witnesses=1,
        touched_requires_clean_witness=False,
    )


def test_replay_resolves_witnesses_and_attributes_workspaces(
    backtest: ModuleType, tmp_path: Path
) -> None:
    repo, first, second = _fixture_repo(tmp_path)
    artifacts = tmp_path / "artifacts"
    witness_meta = artifacts / "witness" / "agent_meta.json"
    subject_meta = artifacts / "subject" / "agent_meta.json"
    witness_meta.parent.mkdir(parents=True)
    subject_meta.parent.mkdir(parents=True)
    witness_meta.write_text(
        json.dumps(
            {
                "name": "witness",
                "workspace_num": 2,
                "run_started_at": "1970-01-01T00:00:05Z",
            }
        ),
        encoding="utf-8",
    )
    subject_meta.write_text(
        json.dumps(
            {
                "name": "subject",
                "workspace_num": 3,
                "run_started_at": "1970-01-01T00:00:25Z",
            }
        ),
        encoding="utf-8",
    )
    witness_log = tmp_path / "witness.log"
    subject_log = tmp_path / "subject.log"
    contaminated_log = tmp_path / "contaminated.log"
    _log(witness_log)
    _log(subject_log)
    _log(contaminated_log, stage="not in historical Justfile")
    scratch = [{"path": "sase_plan_x.md", "status": "untracked", "kind": "untracked"}]
    rows = [
        _run(
            "witness",
            base=first,
            agent="witness",
            created_ts=10,
            settled_ts=20,
            log=witness_log,
        ),
        _run(
            "subject",
            base=second,
            agent="subject",
            created_ts=30,
            settled_ts=40,
            log=subject_log,
            dirty_paths=scratch,
            workspace="ledger-workspace",
        ),
        _run(
            "contaminated",
            base=second,
            agent="contaminated",
            created_ts=30,
            settled_ts=35,
            log=contaminated_log,
        ),
        _run(
            "missing-log",
            base=second,
            agent="missing-log",
            created_ts=30,
            settled_ts=35,
            log=None,
        ),
        _run(
            "missing-head",
            base="f" * 40,
            agent="missing-head",
            created_ts=30,
            settled_ts=35,
            log=subject_log,
        ),
    ]

    report = backtest.replay_runs(
        _namespace(repo, artifacts, tmp_path / "out"), deepcopy(rows)
    )

    assert report["counts"] == {
        "selected_runs": 2,
        "known_items": 1,
        "known_on_added_or_untracked": 0,
        "known_items_in_runs_with_untracked_paths": 1,
        "workspace_attribution": {"ledger": 1, "agent_meta": 1, "none": 0},
    }
    assert report["excluded_runs"] == {
        "contaminated_stage": 1,
        "missing_log": 1,
        "unresolvable_head": 1,
    }
    item = report["sample"][0]
    assert item["extractor"] == "symvision"
    assert item["workspace"] == "ledger-workspace"
    assert item["locator_unchanged_since_witness"] is True
    assert item["witnesses"] == [
        {
            "run_id": "witness",
            "agent": "witness",
            "workspace": "2",
            "base_head": first,
            "base_equals_subject": False,
            "clean_tree": True,
            "dirty_paths": [],
            "selection_source": False,
            "settled_ts": 20,
        }
    ]
    audit = (tmp_path / "out" / "audit.md").read_text(encoding="utf-8")
    assert "Witnesses (run/agent/workspace/base12/clean)" in audit
    header, separator, first_row = audit.splitlines()[2:5]
    assert header.count(" | ") == separator.count(" | ") == first_row.count(" | ")
    assert "KNOWN on added files" in audit
    assert "KNOWN-but-touched" in audit
    same_seed = backtest.replay_runs(
        _namespace(repo, artifacts, tmp_path / "out-again"), deepcopy(rows)
    )
    assert same_seed["sample"] == report["sample"]
    assert backtest._locator_is_added(repo, second, ["sase_plan_x.md"], scratch)
