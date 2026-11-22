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

import pytest

_HEAVY_MODULES = (
    "sase.ace.tui",
    "sase.agents_sync",
    "sase.axe.lumberjack",
    "sase.axe.orchestrator",
    "sase.llm_provider",
    "sase.macro",
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
            "sase.macro",
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
            "sase.macro",
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


def test_claim_and_auto_restart_jobs_import_no_scheduler_or_tui() -> None:
    """The waits-lane jobs reworked by claim-scans stay off the heavy graph."""
    _run_probe(
        """
        import sys
        import sase.scripts.sase_chop_bead_claim_checks

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.llm_provider",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )
    _run_probe(
        """
        import sys
        import sase.scripts.sase_chop_agent_auto_restart
        import sase.agent.auto_restart.healer_target_rows

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.bead.sync",
            "sase.llm_provider",
            "sase.macro",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )


_HOOKS_LANE_JOB_SCRIPTS = (
    "sase.scripts.sase_chop_hook_checks",
    "sase.scripts.sase_chop_mentor_checks",
    "sase.scripts.sase_chop_workflow_checks",
    "sase.scripts.sase_chop_pending_checks_poll",
    "sase.scripts.sase_chop_comment_zombie_checks",
    "sase.scripts.sase_chop_suffix_transforms",
    "sase.scripts.sase_chop_orphan_cleanup",
    "sase.scripts.sase_chop_stale_running_cleanup",
)


@pytest.mark.parametrize("script_module", _HOOKS_LANE_JOB_SCRIPTS)
def test_hooks_lane_job_script_import_excludes_heavy_packages(
    script_module: str,
) -> None:
    """Every hooks-lane job (spawned every few seconds) boots on the builtin SDK only."""
    _run_probe(
        f"""
        import sys
        import {script_module}

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.axe.hook_jobs",
            "sase.llm_provider",
            "sase.macro",
            "sase.monitor",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )


def test_stale_running_sweep_closure_excludes_monitor_and_llm_graphs() -> None:
    """The 5 s stale sweep's modules stay off the monitor-start/LLM/notification graphs.

    ``stale_running_cleanup`` runs on the hooks lane's ``always`` trigger, so
    its import closure is the spawn floor. Each heavy package below used to
    load through a package ``__init__`` or a facade import on that path.
    """
    _run_probe(
        """
        import importlib
        import sys

        for name in (
            "sase.scripts.sase_chop_stale_running_cleanup",
            "sase.axe.hook_jobs",
            "sase.ace.scheduler.stale_running_sweep",
            "sase.ace.scheduler.stale_running_leak",
            "sase.ace.scheduler._stale_running_hijack",
            "sase.monitor.claims",
            "sase.monitor.store",
            "sase.monitor.reconcile",
            "sase.monitor.settlement_fresh_owner",
            "sase.procs.store",
            "sase.agent.hijack.ledger",
            "sase.turns._workspace_retention.pending",
            "sase.turns._workspace_retention.evidence",
            "sase.turns.workspace_retention_surface",
            "sase.workspace_provider.lookup",
        ):
            importlib.import_module(name)

        heavy = [
            "sase.llm_provider",
            "sase.monitor.start",
            "sase.monitor.member",
            "sase.monitor.settlement",
            "sase.monitor.followup",
            "sase.monitor.proc_adapter",
            "sase.agent.hijack.preview",
            "sase.agent.hijack.recover",
            "sase.notifications.store",
            "sase.ace.tui",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
            "sase.agents_sync",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )


def test_wait_checks_job_imports_no_scheduler_tui_or_agents_sync() -> None:
    """The agent_waits job reworked by wait-pulse stays off the heavy graph.

    It already imports ``sase.llm_provider`` and ``sase.macro`` through wait
    resolution, so those are not asserted here.
    """
    _run_probe(
        """
        import sys
        import sase.scripts.sase_chop_wait_checks

        heavy = [
            "sase.ace.tui",
            "sase.agents_sync",
            "sase.axe.lumberjack",
            "sase.axe.orchestrator",
        ]
        present = [name for name in heavy if name in sys.modules]
        assert not present, present
        """
    )
