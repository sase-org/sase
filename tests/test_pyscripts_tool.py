"""Tests for tools/pyscripts-260801 validator."""

from __future__ import annotations

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "pyscripts-260801"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("pyscripts_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "pyscripts_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_stale_cache_only_directory_is_not_placement_target(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )

    tools_dir = repo / "tools"
    tools_dir.mkdir()
    (tools_dir / "my_script.py").write_text(
        "#!/usr/bin/env python3\nprint('hello')\n",
        encoding="utf-8",
    )

    nested_dir = repo / "nested" / "sub"
    nested_dir.mkdir(parents=True)
    (nested_dir / "caller.py").write_text(
        "# references my_script.py\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    stale_cache_dir = repo / "nested" / "tools" / "__pycache__"
    stale_cache_dir.mkdir(parents=True)
    (stale_cache_dir / "x.pyc").write_bytes(b"\x00\x00\x00\x00")

    tool = _load_tool()

    # With only a __pycache__ directory, nested/tools/ has no collectable
    # scripts and must not trigger a Rule 2 closer-directory violation.
    violations = tool._validate(repo)
    assert violations == []
    assert tool.main([str(repo)]) == 0

    # Once nested/tools/ holds a real script, it becomes a valid placement target.
    (repo / "nested" / "tools" / "other.py").write_text(
        "#!/usr/bin/env python3\n",
        encoding="utf-8",
    )
    violations_after = tool._validate(repo)
    rule_2_violations = [v for v in violations_after if v.rule == 2]
    assert len(rule_2_violations) == 1
    assert rule_2_violations[0].script_path == tools_dir / "my_script.py"
    assert "nested/tools" in rule_2_violations[0].message
    assert tool.main([str(repo)]) == 1


def test_markdown_only_directory_is_not_placement_target(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )

    tools_dir = repo / "tools"
    tools_dir.mkdir()
    (tools_dir / "my_script.py").write_text(
        "#!/usr/bin/env python3\nprint('hello')\n",
        encoding="utf-8",
    )

    nested_dir = repo / "nested" / "sub"
    nested_dir.mkdir(parents=True)
    (nested_dir / "caller.py").write_text(
        "# references my_script.py\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    # Documentation-only directory (.md) is skipped by _collect_scripts.
    doc_dir = repo / "nested" / "tools"
    doc_dir.mkdir(parents=True)
    (doc_dir / "README.md").write_text(
        "# Documentation only\n",
        encoding="utf-8",
    )

    tool = _load_tool()
    assert tool._validate(repo) == []
    assert tool.main([str(repo)]) == 0
