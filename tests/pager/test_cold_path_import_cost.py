"""Cold-path import-weight regression tests for the pager startup diet.

``sase pager --plain`` must start without importing the ACE TUI stack: every
probe below imports one cold-path entry point in a fresh subprocess (the
pattern from ``tests/memory/test_history_import_cost.py``) and fails when a
heavy module rode along.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_PROBE_TIMEOUT = 120


def _heavy_modules(import_statement: str, watched: tuple[str, ...]) -> str:
    """Import *import_statement* in a subprocess and report watched modules."""
    watched_repr = repr(tuple(watched))
    probe = (
        "import sys;"
        f"{import_statement};"
        f"watched = {watched_repr};"
        "heavy = [name for name in sys.modules if any("
        "name == prefix or name.startswith(prefix + '.')"
        " for prefix in watched)];"
        "print(','.join(sorted(heavy)));"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=_PROBE_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout.strip()


_COLD_PATH_WATCHED = (
    "textual",
    "sase.ace.tui.widgets.prompt_panel",
    "sase.ace.tui.actions",
    "sase.macro",
    "sase.notification_gates",
    "sase.finalizers",
    "sase.artifact_cli.doctor",
)


def test_pager_document_import_avoids_tui_stack() -> None:
    """Importing the pager document model stays off the TUI stack."""
    heavy = _heavy_modules("import sase.pager.document", _COLD_PATH_WATCHED)
    assert heavy == "", f"sase.pager.document loaded heavy modules: {heavy}"


def test_pager_handler_import_avoids_tui_stack() -> None:
    """Importing the pager CLI handler stays off the TUI stack."""
    heavy = _heavy_modules("import sase.main.pager_handler", _COLD_PATH_WATCHED)
    assert heavy == "", f"sase.main.pager_handler loaded heavy modules: {heavy}"


def test_pager_screen_import_avoids_interactive_only_modules() -> None:
    """Importing the pager screen stays off interactive-only modules."""
    heavy = _heavy_modules(
        "import sase.pager.screen",
        (
            "sase.ace.tui.widgets.prompt_panel",
            "sase.ace.tui.actions.agents",
            "sase.notification_gates",
            "sase.finalizers",
        ),
    )
    assert heavy == "", f"sase.pager.screen loaded heavy modules: {heavy}"


def test_bead_cli_show_batch_import_avoids_textual() -> None:
    """Importing the bead show batch builder stays off Textual."""
    heavy = _heavy_modules("import sase.bead.cli_show_batch", ("textual",))
    assert heavy == "", f"sase.bead.cli_show_batch loaded Textual: {heavy}"


def test_leaf_reexports_are_single_sourced() -> None:
    """ACE facades re-export the pager leaf objects (no forked copies)."""
    from sase.ace.tui.actions.navigation import jump_hints as ace_jump_hints
    from sase.ace.tui.util import lazy_syntax
    from sase.ace.tui.widgets.prompt_panel import _file_path_hints, _hint_caps
    from sase.pager import hint_budgets, jump_hints, path_hints

    assert ace_jump_hints.build_jump_hint_maps is jump_hints.build_jump_hint_maps
    assert ace_jump_hints.match_jump_hint is jump_hints.match_jump_hint
    assert ace_jump_hints.normalize_jump_key is jump_hints.normalize_jump_key
    assert ace_jump_hints.JUMP_HINT_CHARS is jump_hints.JUMP_HINT_CHARS
    assert (
        ace_jump_hints.PAGER_RESERVED_JUMP_COMMAND_KEYS
        is jump_hints.PAGER_RESERVED_JUMP_COMMAND_KEYS
    )
    assert ace_jump_hints.JumpHintMatchOutcome is jump_hints.JumpHintMatchOutcome
    assert _file_path_hints.iter_pager_file_path_matches is (
        path_hints.iter_pager_file_path_matches
    )
    assert _file_path_hints.iter_file_path_matches is path_hints.iter_file_path_matches
    assert _file_path_hints.file_hint_match_span is path_hints.file_hint_match_span
    assert _hint_caps.bound_hint_content is hint_budgets.bound_hint_content
    assert _hint_caps.HintContentBudget is hint_budgets.HintContentBudget
    assert lazy_syntax.truncate_plain_content is hint_budgets.truncate_plain_content
    assert lazy_syntax.PLAIN_RENDER_MAX_BYTES is hint_budgets.PLAIN_RENDER_MAX_BYTES
    assert lazy_syntax.PLAIN_RENDER_MAX_LINES is hint_budgets.PLAIN_RENDER_MAX_LINES


def test_leaf_plan_prefix_matches_canonical() -> None:
    """The leaf's inlined plan prefix must equal the canonical constant."""
    from sase.pager.hint_budgets import _LOGICAL_PLAN_REFERENCE_PREFIX
    from sase.sdd.plan_refs import PLAN_REFERENCE_PREFIX

    assert _LOGICAL_PLAN_REFERENCE_PREFIX == PLAN_REFERENCE_PREFIX


def test_plain_file_run_skips_repo_inventory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain local-file run builds no repo inventory."""
    from sase.artifact_ref_context import collect_repo_inventory
    import sase.artifact_ref_context as artifact_ref_context
    from sase.main import pager_handler
    from sase.main.parser import create_parser

    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def counting_inventory(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return collect_repo_inventory(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        artifact_ref_context, "collect_repo_inventory", counting_inventory
    )
    monkeypatch.chdir(tmp_path)
    args = create_parser(only="pager").parse_args(["pager", "--plain", str(target)])
    assert pager_handler.handle_pager_command(args) == 0
    assert calls == [], f"plain file run built repo inventory {len(calls)} time(s)"


def test_interactive_file_build_still_discovers_kinds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interactive file build still discovers configured scan kinds."""
    from sase.main import pager_handler

    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    document = pager_handler._build_pager_document([str(target)], paint_links=True)
    assert document.sections[0].known_kinds != ()
    plain = pager_handler._build_pager_document([str(target)], paint_links=False)
    assert plain.sections[0].known_kinds == ()
    assert plain.sections[0].plain_text == document.sections[0].plain_text
