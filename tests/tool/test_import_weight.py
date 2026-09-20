"""A foreground `sase tool run` must not pay for the provider/xprompt stack."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.config.tools import tool_project_identity


HEAVY_PREFIXES = ("sase.llm_provider", "sase.xprompt")


def test_tool_modules_do_not_import_the_provider_stack() -> None:
    # `sase tool run -- true` measured ~0.35 s slower than `sase proc list` while
    # observe.py imported git helpers through the `sase.llm_provider` package.
    code = (
        "import sys\n"
        "import sase.tool.executor, sase.tool.query, sase.tool.observe\n"
        f"heavy = sorted(m for m in sys.modules if m.startswith({HEAVY_PREFIXES!r}))\n"
        "print(heavy)\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_project_identity_prefers_env_and_falls_back_to_the_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    project = tmp_path / "named-project"
    (project / "sase").mkdir(parents=True)
    (project / "sase" / "sase.yml").write_text("tools: {}\n", encoding="utf-8")
    monkeypatch.chdir(project)
    monkeypatch.delenv("SASE_PROJECT", raising=False)
    monkeypatch.delenv("SASE_PROJECT_NAME", raising=False)
    assert tool_project_identity() == "named-project"
    monkeypatch.setenv("SASE_PROJECT", "from-env")
    assert tool_project_identity() == "from-env"
