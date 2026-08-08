"""Tests for the retired test wait-helper lint tool."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_test_wait_helpers"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_test_wait_helpers_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "check_test_wait_helpers_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_finds_private_wait_until_helpers(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_bad.py").write_text(
        "async def _wait_until(pilot, predicate):\n"
        "    while not predicate():\n"
        "        await pilot.pause()\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == [
        tool.Finding(root / "test_bad.py", 1, "private-wait-until")
    ]


def test_domain_specific_wait_names_are_allowed(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "harness.py").write_text(
        "def _wait_for_condition(predicate):\n"
        "    while not predicate():\n"
        "        pass\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == []


def test_finds_inline_bounded_pilot_pause_waits(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_bad.py").write_text(
        "async def test_wait(pilot, modal):\n"
        "    for _ in range(20):\n"
        "        await pilot.pause()\n"
        "        if modal.ready:\n"
        "            break\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == [
        tool.Finding(root / "test_bad.py", 2, "inline-pilot-pause-wait")
    ]


def test_repeated_pilot_actions_are_allowed(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_ok.py").write_text(
        "async def test_cycle(pilot, button):\n"
        "    labels = []\n"
        "    for _ in range(4):\n"
        "        button.press()\n"
        "        await pilot.pause()\n"
        "        labels.append(str(button.label))\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == []


def test_finds_raw_ace_prompt_panel_text_injections(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_bad.py").write_text(
        "async def test_prompt(page):\n"
        "    panel = page.app.query_one('#agent-prompt-panel', AgentPromptPanel)\n"
        "    panel.update(Text('needle'))\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == [
        tool.Finding(root / "test_bad.py", 3, "raw-agent-prompt-panel-text")
    ]


def test_prompt_panel_unit_updates_are_allowed(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_ok.py").write_text(
        "def test_prompt_panel_unit():\n"
        "    panel = AgentPromptPanel()\n"
        "    panel.update(Text('unit-owned document'))\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == []


def test_prompt_panel_aliases_do_not_leak_between_functions(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_ok.py").write_text(
        "def test_full_ace_page(page):\n"
        "    panel = page.app.query_one('#agent-prompt-panel', AgentPromptPanel)\n"
        "    assert panel is not None\n"
        "\n"
        "def test_prompt_panel_unit():\n"
        "    panel = AgentPromptPanel()\n"
        "    panel.update(Text('unit-owned document'))\n",
        encoding="utf-8",
    )

    tool = _load_tool()

    assert tool.find_forbidden_helpers((root,)) == []
