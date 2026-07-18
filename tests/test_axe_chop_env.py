"""Chop environment composition and secret-reference coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.chop_env import (
    chop_target_env,
    resolve_chop_env,
)


def test_resolve_chop_env_supports_literals_env_files_and_pass(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "token"
    secret_file.write_text("from-file\n", encoding="utf-8")
    completed = subprocess.CompletedProcess(
        ["pass", "show", "service/token"],
        0,
        stdout="from-pass\nmetadata\n",
        stderr="",
    )

    with patch("sase.axe.chop_env.subprocess.run", return_value=completed):
        resolved = resolve_chop_env(
            {
                "LITERAL": "value",
                "FROM_ENV": {"env": "SOURCE_TOKEN"},
                "FROM_FILE": {"file": str(secret_file)},
                "FROM_PASS": {"pass": "service/token"},
            },
            environ={"SOURCE_TOKEN": "from-env"},
        )

    assert resolved == {
        "LITERAL": "value",
        "FROM_ENV": "from-env",
        "FROM_FILE": "from-file",
        "FROM_PASS": "from-pass",
    }


def test_resolve_chop_env_fails_without_exposing_other_secret_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        resolve_chop_env(
            {
                "SAFE": "do-not-leak-this",
                "TOKEN": {"env": "MISSING_TOKEN"},
            },
            environ={},
        )

    assert "TOKEN" in str(exc_info.value)
    assert "MISSING_TOKEN" in str(exc_info.value)
    assert "do-not-leak-this" not in str(exc_info.value)


def test_chop_target_env_is_stable_and_rejects_name_collisions() -> None:
    assert chop_target_env(
        "sase-core",
        {"name": "sase-core", "priority": 2, "metadata": {"b": 1, "a": 2}},
    ) == {
        "SASE_CHOP_TARGET_KEY": "sase-core",
        "SASE_CHOP_TARGET_METADATA": '{"a":2,"b":1}',
        "SASE_CHOP_TARGET_NAME": "sase-core",
        "SASE_CHOP_TARGET_PRIORITY": "2",
    }

    with pytest.raises(ValueError, match="collide"):
        chop_target_env("target", {"foo-bar": 1, "foo_bar": 2})
