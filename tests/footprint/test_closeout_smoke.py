"""Closeout end-to-end smoke: CLI and TUI hits flow into the review markdown.

Drives real CLI processes and one TUI pilot session against a sandboxed
``SASE_HOME``, folds the spool, and asserts the report, card, decision flow,
and privacy floor (no secrets leak into spool, ledger output, or markdown).

Export preview/import is intentionally out of scope: no export subcommand,
facade function, or catalog ID exists in this tree (see the phase bead notes).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.commands.execute import execute_command
from sase.ace.tui.commands.types import CommandExecutor, CommandSpec
from sase.ace.tui.modals.help_modal.modal import HelpModal
from sase.footprint import _tui


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _base_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["SASE_HOME"] = str(home)
    env["SASE_FOOTPRINT"] = "test"
    env["SASE_PYTEST_SANDBOX_DIR"] = str(home)
    env.pop("SASE_MODE", None)
    return env


def _run_sase(argv: list[str], home: Path, extra_env: dict[str, str] | None = None):
    env = _base_env(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "sase", *argv],
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _spool_text(home: Path) -> str:
    spool = home / "footprint" / "spool"
    return "\n".join(
        path.read_text(encoding="ascii") for path in sorted(spool.glob("*.jsonl"))
    )


async def test_closeout_end_to_end_smoke(tmp_path: Path) -> None:
    home = tmp_path / "home"
    secret = "smoke-secret-project-must-not-be-recorded"
    agent_name = "smoke-agent-name-must-not-be-recorded"

    # In-process TUI hits need the same sandbox env the subprocesses get.
    saved_env = dict(os.environ)
    os.environ["SASE_HOME"] = str(home)
    os.environ["SASE_FOOTPRINT"] = "test"
    os.environ["SASE_PYTEST_SANDBOX_DIR"] = str(home)
    try:
        await _drive_smoke(home, tmp_path, secret, agent_name)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        _tui._reset_for_tests()


async def _drive_smoke(
    home: Path, tmp_path: Path, secret: str, agent_name: str
) -> None:
    # 1. CLI hits: a normal command, help, a usage error, and an agent run.
    assert _run_sase(["version"], home).returncode == 0
    assert _run_sase(["footprint", "mode"], home).returncode == 0
    assert _run_sase(["footprint", "mode", "--help"], home).returncode == 0
    bad = _run_sase(["footprint", "mode", "impossible"], home)
    assert bad.returncode == 2
    assert _run_sase(["version"], home, {"SASE_AGENT_NAME": agent_name}).returncode == 0
    assert _run_sase(["footprint", "catalog", "--area", secret], home).returncode == 0

    # 2. TUI hits: one key action, one palette command, one modal.
    _tui._reset_for_tests()
    async with AcePage(initial_tab="artifacts") as page:
        _tui._reset_for_tests()
        assert await page.app.run_action("dismiss_toasts") is True
        execute_command(
            page.app,
            CommandSpec(
                id="app.dismiss_toasts",
                label="Dismiss toasts",
                key_sequence=("Z",),
                key_display="Z",
                category="Navigation",
                tabs=("artifacts", "agents", "services"),
                executor=CommandExecutor(kind="app_action", action="dismiss_toasts"),
            ),
        )
        page.app.push_screen(HelpModal("agents", registry=page.app._keymap_registry))
        await page.pause()
        _tui.flush_now()
    _tui._reset_for_tests()

    spool_text = _spool_text(home)
    assert "cli:version" in spool_text
    assert "tui:app.dismiss_toasts" in spool_text
    assert "view:modal.help" in spool_text
    forbidden_tokens = [secret, agent_name, str(home), str(tmp_path)]
    inherited_agent = os.environ.get("SASE_AGENT_NAME")
    if inherited_agent:
        forbidden_tokens.append(inherited_agent)
    for forbidden in forbidden_tokens:
        assert forbidden not in spool_text

    # 3. Fold (status folds-if-stale first), then read the review markdown.
    folded = _run_sase(["footprint", "status", "-f", "json"], home)
    assert folded.returncode == 0, folded.stderr
    status = json.loads(folded.stdout)
    assert status["spool_bytes_pending"] == 0

    # Sandbox CLI runs record actor "unknown" (no TTY, agent markers vary), so
    # the review assertions use the everyone scope.
    maps: dict[str, str] = {}
    for lens in ("map", "cold", "agent-only"):
        result = _run_sase(
            ["footprint", "list", "-l", lens, "-a", "everyone", "-f", "markdown"],
            home,
        )
        assert result.returncode == 0, result.stderr
        maps[lens] = result.stdout
    assert maps["map"].startswith("# Footprint")
    assert "`cli.version`" in maps["map"]
    assert (
        "`tui:app.dismiss_toasts`" in maps["agent-only"]
        or "`cli:version`" in maps["agent-only"]
    )

    card = _run_sase(
        ["footprint", "show", "cli:version", "-a", "everyone", "-f", "markdown"],
        home,
    )
    assert card.returncode == 0, card.stderr
    assert card.stdout.startswith("# `cli:version`")

    # 4. Decide flow lands in the decisions lens.
    decide = _run_sase(
        ["footprint", "decide", "cli:version", "keep", "-r", "agent_facing"], home
    )
    assert decide.returncode == 0, decide.stderr
    decisions = _run_sase(
        ["footprint", "list", "-l", "decisions", "-a", "everyone", "-f", "markdown"],
        home,
    )
    assert decisions.returncode == 0, decisions.stderr
    assert "`cli:version`" in decisions.stdout

    # The first fold wrote the one-time disclosure notification to the inbox.
    inbox = home / "notifications" / "notifications.jsonl"
    assert inbox.exists()
    assert "footprint.disclosure" in inbox.read_text(encoding="utf-8")

    # 5. Privacy floor: rendered output carries counts, never secrets.
    rendered = "\n".join([*maps.values(), card.stdout, decisions.stdout])
    for forbidden in forbidden_tokens:
        assert forbidden not in rendered
