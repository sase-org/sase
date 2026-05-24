from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _evaluate_sase_core_dir(env_vars: dict[str, str]) -> str:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.update(env_vars)

    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--evaluate", "sase_core_dir"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("env_vars", "expected"),
    [
        (
            {
                "SASE_CORE_DIR": "/tmp/explicit-sase-core",
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core",
            },
            "/tmp/explicit-sase-core",
        ),
        (
            {
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/legacy-core",
            },
            "/tmp/sibling-sase-core",
        ),
        (
            {"SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core"},
            "/tmp/sibling-sase-core",
        ),
        ({}, "../sase-core"),
    ],
)
def test_justfile_sase_core_dir_precedence(
    env_vars: dict[str, str], expected: str
) -> None:
    assert _evaluate_sase_core_dir(env_vars) == expected
