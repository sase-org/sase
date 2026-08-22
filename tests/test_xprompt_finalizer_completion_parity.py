"""Parity coverage for ACE and LSP finalizer completion."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.directive_completion import (
    DirectiveCatalogPlaceholder,
    build_directive_clause_candidates,
    classify_directive_completion,
)
from tests._xprompt_directive_completion_parity_helpers import (
    _OPTIONAL_FINALIZER_ROWS,
    _write_failing_helper,
)
from tests._xprompt_directive_completion_parity_lsp import (
    LspSession,
    _only_lsp,
    _surface_rows,
    _utf16_len,
)
from tests._xprompt_directive_completion_parity_surface import (
    _ace_and_lsp_rows,
    _ace_surface_rows,
    _selectable_surface_rows,
)


def test_ace_and_lsp_finalizer_add_rows_match(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:")

    assert [row.insertion for row in ace_rows] == ["commit", "lint", "zoom"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert ace_rows[0].detail == "builtin@commit · required"
    assert ace_rows[1].detail == "builtin@command · default"
    assert ace_rows[2].detail == "plugin@zoom · optional"
    assert "Required for this launch." in ace_rows[0].documentation
    assert "Provider: `builtin@commit`" in ace_rows[0].documentation
    assert "Depends on: `format`" in ace_rows[1].documentation
    assert "Retry policy: 2 attempts" in ace_rows[1].documentation
    assert "Retry policy: 1 attempt" in ace_rows[2].documentation


def test_ace_and_lsp_finalizer_remove_omits_required(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:!")

    assert [row.insertion for row in ace_rows] == ["!lint", "!zoom"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert all(row.detail.startswith("remove · ") for row in ace_rows)
    assert "Remove `lint` from the launch selection." in ace_rows[0].documentation
    assert not any(row.insertion in {"!commit", "none"} for row in ace_rows)


def test_ace_and_lsp_none_suppressed_when_required_exists(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:n")

    assert [row.insertion for row in ace_rows] == []
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_ace_and_lsp_none_available_when_clear_is_legal(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(
        tmp_path,
        "%final:n",
        finalizer_inventory=_OPTIONAL_FINALIZER_ROWS,
    )

    assert [row.insertion for row in ace_rows] == ["none"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert ace_rows[0].detail == "clear"
    assert "Clear the configured finalizer selection" in ace_rows[0].documentation


def test_ace_and_lsp_finalizer_repeated_directive_matches(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:none %final:l")

    assert [row.insertion for row in ace_rows] == ["lint"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_ace_and_lsp_finalizer_parenthesized_clause_replacement(
    tmp_path: Path,
) -> None:
    text = "%final(commit, !l"
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, text)

    assert [row.insertion for row in ace_rows] == ["!lint"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    lsp = _only_lsp(lsp_rows)
    assert lsp.raw is not None
    assert lsp.raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": 15},
        "end": {"line": 0, "character": _utf16_len(text)},
    }


def test_ace_and_lsp_finalizer_utf16_replacement_next_to_non_ascii(
    tmp_path: Path,
) -> None:
    text = "🙂 %final(café, c"
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, text)

    assert [row.insertion for row in ace_rows] == ["commit"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    lsp = _only_lsp(lsp_rows)
    assert lsp.raw is not None
    prefix = "🙂 %final(café, "
    assert lsp.raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": _utf16_len(prefix)},
        "end": {"line": 0, "character": _utf16_len(text)},
    }


def test_finalizer_helper_failure_degrades_without_invented_rows(
    tmp_path: Path,
) -> None:
    helper = _write_failing_helper(tmp_path)
    clause = classify_directive_completion("%final:", len("%final:"))
    assert clause is not None
    ace_candidates, _ = build_directive_clause_candidates(
        clause,
        finalizers_state="unavailable",
    )
    with LspSession(tmp_path, helper=helper) as lsp:
        lsp_rows = lsp.complete("%final:")

    assert len(ace_candidates) == 1
    placeholder = ace_candidates[0].metadata
    assert isinstance(placeholder, DirectiveCatalogPlaceholder)
    assert placeholder.kind == "unavailable"
    assert placeholder.catalog == "finalizers"
    assert ace_candidates[0].insertion == ""
    assert [row.insertion for row in lsp_rows] == []
    assert _selectable_surface_rows(_ace_surface_rows(ace_candidates)) == []
    assert _selectable_surface_rows(lsp_rows) == []
