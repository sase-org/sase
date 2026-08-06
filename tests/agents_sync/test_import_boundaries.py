from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sase.workspace_provider.marker import CheckoutMarker, MARKER_DIR, MARKER_FILENAME
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"


def _subprocess_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(_SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    env["SASE_HOME"] = str(tmp_path / "sase-home")
    env["SASE_PYTEST_SANDBOX_DIR"] = str(tmp_path)
    return env


@pytest.mark.parametrize(
    "module_name",
    ("sase.agents_sync", "sase.agents_sync.links", "sase.agents_sync.bead_links"),
)
def test_agents_sync_imports_in_fresh_interpreter(
    module_name: str,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=_REPO_ROOT,
        env=_subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_hosted_links_imports_before_agents_sync_in_fresh_interpreter(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sase.sdd.hosted_links import resolve_hosted_branch",
        ],
        cwd=_REPO_ROOT,
        env=_subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, combined_output
    assert "partially initialized" not in combined_output


def test_agents_sync_does_not_import_ace_layer() -> None:
    violations: list[str] = []
    for source_path in sorted((_SRC_DIR / "sase" / "agents_sync").rglob("*.py")):
        relative = source_path.relative_to(_REPO_ROOT)
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(relative)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sase.ace" or alias.name.startswith("sase.ace."):
                        violations.append(
                            f"{relative}:{node.lineno} import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level and (module == "ace" or module.startswith("ace.")):
                    violations.append(
                        f"{relative}:{node.lineno} from {'.' * node.level}{module}"
                    )
                if module == "sase.ace" or module.startswith("sase.ace."):
                    violations.append(f"{relative}:{node.lineno} from {module}")

    assert violations == []


def test_bead_work_plan_file_smoke_reaches_validation(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    primary = tmp_path / "primary"
    checkout.mkdir()
    primary.mkdir()
    marker = CheckoutMarker(
        project_name="test-project",
        project_key="test-project",
        workspace_num=1,
        primary_workspace_dir=str(primary),
        registry_path=str(primary / ".sase" / "registry.json"),
    )
    marker_path = checkout / MARKER_DIR / MARKER_FILENAME
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(marker.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    plan_path = checkout / "epic.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sase.main.entry",
            "bead",
            "work",
            str(plan_path),
            "--dry-run",
        ],
        cwd=checkout,
        env=_subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, combined_output
    assert "Validated" in result.stdout
    assert "ImportError" not in combined_output
    assert "partially initialized" not in combined_output
