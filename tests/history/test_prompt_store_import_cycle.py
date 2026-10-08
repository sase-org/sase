"""Fresh-interpreter regression tests for the prompt_store import cycle.

`sase.history.prompt_store` re-exports names from
`sase.history.prompt_store_mutations`, so the mutations module must never
import the facade at module load: whichever module is imported first has to
work. Warm test processes hide this bug, so each case runs a fresh
interpreter via subprocess (see bead sase-1h2).
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _run_fresh(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_mutations_import_first_succeeds() -> None:
    """Importing prompt_store_mutations cold exposes effective_prompt_origin."""
    result = _run_fresh(
        "import sase.history.prompt_store_mutations as m; "
        "assert callable(m.effective_prompt_origin); "
        "print('ok')"
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_mutations_import_first_keeps_facade_reexports() -> None:
    """Facade re-exports still resolve when the mutations module loads first."""
    result = _run_fresh(
        "import sase.history.prompt_store_mutations; "
        "from sase.history.prompt_store import ("
        "add_or_update_prompt, "
        "record_failed_launch_prompt, "
        "rewrite_prompt_text_exact); "
        "print('ok')"
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


@pytest.mark.parametrize(
    "caller",
    [
        "sase.agent.launch_cwd_agents",
        "sase.agent.launch_cwd_bead_work",
        "sase.agent.launch_provenance",
    ],
)
def test_lazy_caller_import_first_succeeds(caller: str) -> None:
    """Each lazy caller imports cold, then its lazy dependency resolves."""
    result = _run_fresh(
        f"import {caller}; "
        "from sase.history.prompt_store_mutations import "
        "effective_prompt_origin; "
        "assert callable(effective_prompt_origin); "
        "print('ok')"
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
