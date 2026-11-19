"""CLI acceptance: a real ``sase tool run check`` attaches the exact owner.

Each case builds an isolated fixture: its own ``SASE_HOME`` ToolRun store, a
project whose bead event store holds one open CI task naming the failing
pytest node, and a disposable ``check`` tool that runs a really failing
pytest node through the real ``tools/run_silent`` stage helper. Nothing is
mocked: the subprocesses run the real gatherer, the Rust candidate
projection, the owner matcher, and persistence, then read the result back
through ``sase tool show -j`` and ``sase tool failures -t check -j``.

The agent-attributed case exercises normal stage-first triage (the stage
classifies with no owners, final settle attaches them); the human case
exercises the fresh-settle path. Both keep the failing run's exit code.
"""

from __future__ import annotations

import importlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache

_CORE = importlib.import_module("sase_core_rs")

pytestmark = pytest.mark.skipif(
    not hasattr(_CORE, "bead_triage_owner_candidates"),
    reason="bead_triage_owner_candidates binding is not in this wheel",
)

ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"
NODE = "tests/test_owner_probe.py::test_owner"
_KEEP_ENV = frozenset({"SASE_HOME", "SASE_PYTEST_SANDBOX_DIR"})


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=Fixture",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_owner_probe.py").write_text(
        "def test_owner():\n    assert 1 == 2\n", encoding="utf-8"
    )
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    # The bead store and its read-model git dir stay out of the fixture
    # repo's status.
    (root / ".gitignore").write_text("sdd/\n", encoding="utf-8")
    pytest_cmd = " ".join(
        shlex.quote(part)
        for part in (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rf",
            "-p",
            "no:cacheprovider",
            NODE,
        )
    )
    stage = (
        f"{shlex.quote(str(RUN_SILENT))} 'test (scoped)' "
        f"env -u PYTEST_ADDOPTS -u PYTEST_CURRENT_TEST {pytest_cmd}"
    )
    finish = f"{shlex.quote(str(RUN_SILENT))} --finish"
    catalog = {
        "tools": {
            "check": {
                "argv": ["bash", "-c", f"{stage} && {finish}"],
                "description": "owner acceptance fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root


def _seed_owner(root: Path) -> str:
    """Create one open CI task naming ``NODE`` in a cache-backed event store."""

    _CORE.bead_init_store(str(root), "sdd/beads", "fx", "fixture@example.invalid")
    beads_dir = root / "sdd" / "beads"
    # A git dir beside the store gives the bead read model a cache location.
    (root / "sdd" / ".git").mkdir()
    created = _CORE.bead_create(
        str(beads_dir),
        {
            "title": "Owner probe fails",
            "issue_type": "task",
            "size": "small",
            "task_type": "ci",
            "task_type_fields": {
                "node_id": NODE,
                "sha": "0" * 40,
                "why_not_flake": "deterministic assertion",
            },
        },
    )
    owner_id = str(created["issue"]["id"])
    # A closed, unrelated history task never becomes an owner.
    _CORE.bead_create(
        str(beads_dir),
        {
            "title": "Unrelated idea",
            "issue_type": "task",
            "size": "small",
            "task_type": "feature",
            "task_type_fields": {
                "proposal": "tests/test_owner_probe.py",
                "why_out_of_scope": "fixture",
            },
        },
    )
    return owner_id


def _env(tmp_path: Path, *, agent: str | None) -> dict[str, str]:
    heim = tmp_path / "home"
    heim.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SASE_") or key in _KEEP_ENV
    }
    env["SASE_HOME"] = str(heim)
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), env.get("PYTHONPATH", "")) if part
    )
    if agent is not None:
        env["SASE_AGENT_NAME"] = agent
    return env


def _sase(
    root: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sase", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _json(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _owner_items(shown: dict[str, Any]) -> list[dict[str, Any]]:
    triage = shown.get("triage") or {}
    return [
        item
        for item in triage.get("items") or []
        if isinstance(item, dict) and item.get("signature")
    ]


@pytest.mark.parametrize(
    ("agent", "stage_first"),
    [("owner-acceptance-agent", True), (None, False)],
    ids=["stage-first", "fresh-settle"],
)
def test_real_check_run_attaches_the_exact_node_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent: str | None,
    stage_first: bool,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    clear_config_cache()
    root = _project(tmp_path)
    owner_id = _seed_owner(root)
    env = _env(tmp_path, agent=agent)

    ran = _sase(root, env, "tool", "run", "check")
    # pytest's failure exit code survives triage unchanged.
    assert ran.returncode == 1, (ran.stdout, ran.stderr)
    assert NODE in ran.stdout + ran.stderr

    listed = _json(_sase(root, env, "tool", "runs", "-j", "-t", "check", "-n", "1"))
    runs = listed.get("runs") or []
    assert len(runs) == 1, listed
    run_id = str(runs[0]["run_id"])

    shown = _json(_sase(root, env, "tool", "show", "-j", run_id))
    expected = [
        {
            "id": owner_id,
            "status": "open",
            "reason": "possible owner",
            "matched_on": "location",
        }
    ]
    items = _owner_items(shown)
    assert items, shown
    item = next(i for i in items if NODE in json.dumps(i))
    assert item["label"]["class"] == "unknown"
    assert item["label"]["possible_owners"] == expected
    # Stage-first triage decided at the failed stage under ``known``
    # continuation; the human run classified only at final settle.
    stages = (shown.get("triage") or {}).get("stages") or []
    decisions = [s["decision"] for s in stages if isinstance(s, dict)]
    assert [d["decision"] for d in decisions] == ["stop"], stages
    assert [d["mode"] for d in decisions] == ["known" if stage_first else "never"]

    failures = _json(_sase(root, env, "tool", "failures", "-t", "check", "-j"))
    groups = [
        group
        for group in failures.get("groups") or []
        if group.get("signature") == item["signature"]
    ]
    assert len(groups) == 1, failures
    assert groups[0]["newest_owners"] == expected
