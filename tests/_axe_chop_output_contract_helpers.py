"""Shared fixtures for axe chop output-contract tests.

Not a conftest so the fixtures only apply when a test file opts in by
importing the re-exported name as an autouse fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context.

    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def _write_context(tmp_path: Path, result_path: Path) -> Path:
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="test",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
        ),
        str(context_path),
    )
    return context_path
