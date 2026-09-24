"""Value-kind coverage ratchet (bead sase-17x.3).

Every non-hidden, value-taking option and every non-remainder positional in
``build_spec()`` must declare a completion ``kind``, carry argparse
``choices``, or carry a free-form ``value_hint``. When this test fails it
names each offending ``(path, dest)`` and the three ways to fix it.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.completion.build import build_spec
from sase.completion.candidates.providers import candidates_for, shipped_kinds
from sase.completion.kinds import RUN_PROMPT_SLOT, ValueKind
from sase.completion.model import CommandSpec


def _all_commands(root: CommandSpec) -> Iterator[CommandSpec]:
    yield root
    for child in root.subcommands:
        yield from _all_commands(child)


def _uncovered_slots() -> list[tuple[tuple[str, ...], str]]:
    """Return ``(path, dest)`` for value slots with no kind, choices, or hint."""
    missing: list[tuple[tuple[str, ...], str]] = []
    for command in _all_commands(build_spec().root):
        for option in command.options:
            if (
                option.takes_value
                and not option.hidden
                and option.choices is None
                and option.kind is None
                and option.value_hint is None
            ):
                missing.append((command.path, option.dest))
        for positional in command.positionals:
            if (
                not positional.is_remainder
                and positional.choices is None
                and positional.kind is None
                and positional.value_hint is None
            ):
                missing.append((command.path, positional.dest))
    return sorted(missing)


def test_every_value_slot_is_kinded_choiced_or_hinted() -> None:
    missing = _uncovered_slots()
    assert not missing, (
        "uncaptioned completion value slots: "
        + ", ".join(f"{'/'.join(path) or 'sase'}:{dest}" for path, dest in missing)
        + ". Fix each slot one of three ways: (1) a ValueKind in "
        "src/sase/completion/kinds.py NAME_TABLE/PATH_OVERRIDES (or "
        "set_completion_kind at the parser), (2) argparse choices= on the "
        "action, or (3) a free-form value_hint in the kinds.py hint table."
    )


def test_run_prompt_slot_keeps_its_bespoke_completion() -> None:
    """``sase run``'s PROMPT slot stays out of the plain-kind catalog."""
    assert RUN_PROMPT_SLOT == (("run",), "prompt")


def test_new_kinds_are_shipped_with_providers() -> None:
    shipped = shipped_kinds()
    assert "gate" in shipped
    assert "tool_run" in shipped
    assert "task_type" in shipped


def test_task_type_candidates_list_registry_slugs() -> None:
    # The registry is compiled in, not home-dependent.
    values = {
        candidate.value
        for candidate in candidates_for("task_type", "", project=None, limit=200)
    }
    assert {"bug", "flake", "memory"} <= values


def test_gate_and_tool_run_providers_are_read_only_and_prompt_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown homes yield empty lists, never tracebacks or prompts."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    assert candidates_for("gate", "", project=None, limit=200) == []
    assert candidates_for("tool_run", "", project=None, limit=200) == []


def test_gate_kind_covers_gate_shell_references() -> None:
    spec = build_spec()
    by_path = {command.path: command for command in _all_commands(spec.root)}
    show = by_path[("gate", "show")]
    assert next(p for p in show.positionals if p.dest == "gate_ref").kind is (
        ValueKind.GATE
    )
    assert next(o for o in show.options if o.dest == "id").kind is ValueKind.GATE
    tool_show = by_path[("tool", "show")]
    assert (
        next(p for p in tool_show.positionals if p.dest == "tool_show_run_id").kind
        is ValueKind.TOOL_RUN
    )
    bead_list = by_path[("bead", "list")]
    assert next(o for o in bead_list.options if o.dest == "task_type").kind is (
        ValueKind.TASK_TYPE
    )


def test_entity_catalog_stays_off_the_forbidden_imports() -> None:
    """The new catalog module imports cleanly without UI-heavy packages."""
    script = (
        "import sys; "
        "import sase.completion.candidates.catalog_entities; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "{'textual', 'rich'} or m == 'sase.ace' or "
        "m.startswith(('sase.ace.', 'sase.sdd.', 'sase.bead.', "
        "'sase.workspace_provider.', 'sase.xprompt.', 'sase.llm_provider.'))]; "
        "sys.exit('forbidden imports: ' + ','.join(bad) if bad else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
