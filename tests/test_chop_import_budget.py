"""Import-cost guards for the chop subprocess entrypoint's import closure.

Every ``sase_chop_*`` console script imports ``sase.chops.sdk`` (or
``sase.chops.builtin`` for builtin chops) before doing any work. These
guards keep that shared import path from regressing back to eagerly
pulling in the scheduler/orchestrator/TUI/LLM/agents-sync import graph
that a chop body never touches.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

_HEAVY_MODULES = (
    "sase.ace.tui",
    "sase.agents_sync",
    "sase.axe.lumberjack",
    "sase.axe.orchestrator",
    "sase.llm_provider",
    "sase.xprompt",
)


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_chop_sdk_import_excludes_heavy_packages() -> None:
    _run_probe(
        """
        import sys
        import sase.chops.sdk

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.llm_provider",
            "sase.xprompt",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )


def test_chop_builtin_import_excludes_heavy_packages() -> None:
    _run_probe(
        """
        import sys
        import sase.chops.builtin

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.axe.check_cycles",
            "sase.axe.hook_jobs",
            "sase.llm_provider",
            "sase.xprompt",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )


def test_chop_script_context_import_does_not_import_axe_scheduler() -> None:
    _run_probe(
        """
        import sys
        import sase.axe.chop_script_context

        assert "sase.axe.lumberjack" not in sys.modules
        assert "sase.axe.orchestrator" not in sys.modules
        assert "sase.axe.status_collector" not in sys.modules
        """
    )


def test_axe_package_getattr_stays_lazy_for_unused_submodules() -> None:
    _run_probe(
        """
        import sys
        import sase.axe.state

        assert "sase.axe.lumberjack" not in sys.modules
        assert "sase.axe.orchestrator" not in sys.modules

        # Accessing a lazy re-export still resolves correctly on demand.
        import sase.axe

        assert sase.axe.Lumberjack.__name__ == "Lumberjack"
        assert "sase.axe.lumberjack" in sys.modules
        """
    )
