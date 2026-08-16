"""Shared fixtures for ``sase var get`` CLI tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.main.parser import create_parser
from sase.main.var_handler import handle_var_command
from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)


def run_var_get(argv: list[str]) -> None:
    """Run ``sase var get`` with *argv* through the real parser and handler."""
    handle_var_command(create_parser().parse_args(["var", "get", *argv]))


def write_current_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variables: dict[str, Any],
) -> Path:
    """Point ``SASE_ARTIFACTS_DIR`` at a fresh artifact dir holding *variables*."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"output_variables": variables}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts


def seed_var_get_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed an indexed multi-project agent history and return the SASE home."""
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260814101010",
        name="build",
        variables={
            "status": "old",
            "results": ["a", "b"],
            "report": {"summary": "old", 'a"b': 1},
        },
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815121212",
        name="build",
        variables={
            "status": "ok",
            "results": ["x", "y"],
            "report": {"summary": "fresh", "nested": {"n": 2}},
            "count": 1,
        },
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815131313",
        name="build.worker",
        variables={"status": "ok", "count": 1.0},
        hidden=True,
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815141414",
        name="research",
        variables={"status": "root"},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815151515",
        name="research.foo",
        variables={"status": "member", "report": {"summary": "from-foo"}},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815161616",
        name="research.foo-bar",
        variables={"status": "hyphen"},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815171717",
        name="2review",
        variables={"status": "digit"},
    )
    write_indexed_agent(
        projects,
        project="other",
        timestamp="20260815181818",
        name="deploy",
        variables={"status": "failed"},
    )
    write_indexed_agent(
        projects,
        project="other",
        timestamp="20260815191919",
        name="build",
        variables={"status": "hidden-other"},
        hidden=True,
    )
    rebuild_home_index(home, projects)
    return home
