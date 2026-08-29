"""Parity coverage for ACE and LSP directive completion."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
import sase_core_rs

from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    classify_directive_completion,
)
from sase.feature_flags import override_flags
from tests._xprompt_directive_completion_parity_helpers import _write_failing_helper
from tests._xprompt_directive_completion_parity_lsp import (
    LspSession,
    _surface_rows,
)
from tests._xprompt_directive_completion_parity_surface import (
    MODEL_ALIAS_DESCRIPTION_PATCH,
    MODEL_ALIAS_NAMES_PATCH,
    MODEL_CATALOG_PATCH,
    _ace_clause_rows,
    _ace_surface_rows,
    _model_alias_description,
    _model_entries,
)


@pytest.fixture(autouse=True)
def _typed_launch_units_off_by_default() -> Iterator[None]:
    """Keep ungated-contract assertions independent of host flag state."""
    with override_flags(typed_launch_units=False):
        yield


def test_ace_and_lsp_directive_name_rows_match(tmp_path: Path) -> None:
    ace_candidates, shared = build_directive_completion_candidates("%")
    assert shared == ""
    ace_rows = _ace_surface_rows(ace_candidates)
    expected_labels: list[str] = []
    for row in sase_core_rs.directive_contract():
        if row.get("feature_flag"):
            continue
        expected_labels.append(f"%{row['name']}")
        expected_labels.extend(
            recipe["label"]
            for recipe in row.get("recipes", [])
            if isinstance(recipe, dict)
        )

    with LspSession(tmp_path) as lsp:
        lsp_rows = lsp.complete("%")

    assert {row.label for row in ace_rows} == set(expected_labels)
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert "%if" not in expected_labels
    assert "%proc" not in expected_labels


def test_ace_and_lsp_include_typed_launch_directives_when_enabled(
    tmp_path: Path,
) -> None:
    with override_flags(typed_launch_units=True):
        ace_candidates, shared = build_directive_completion_candidates("%")
        assert shared == ""
        ace_labels = {row.label for row in _ace_surface_rows(ace_candidates)}
        with LspSession(tmp_path) as lsp:
            lsp_labels = {row.label for row in lsp.complete("%")}

    assert "%if" in ace_labels
    assert "%proc" in ace_labels
    assert ace_labels == lsp_labels


@pytest.mark.parametrize(
    "text",
    [
        "%effort:",
        "%auto:",
        "%repeat:",
        "%xprompts_enabled:",
        "%id(worker, be",
        "%id(worker, cl",
        "%id(worker, fa",
        "%id(worker, tr",
        "%clan(research, su",
        "%clan(research, tr",
        "%wait(",
        "%wait:",
        "%wait(bead=",
        "%model:",
        "%model(me",
        "%model(opus, medium=",
    ],
)
def test_ace_and_lsp_directive_argument_rows_match(
    tmp_path: Path,
    text: str,
) -> None:
    with (
        patch(MODEL_CATALOG_PATCH, return_value=_model_entries()),
        patch(MODEL_ALIAS_NAMES_PATCH, return_value=("medium",)),
        patch(MODEL_ALIAS_DESCRIPTION_PATCH, side_effect=_model_alias_description),
    ):
        ace_rows = _ace_clause_rows(text)
        with LspSession(tmp_path) as lsp:
            lsp_rows = lsp.complete(text)

    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_wait_colon_form_never_advertises_structured_keywords(
    tmp_path: Path,
) -> None:
    with LspSession(tmp_path) as lsp:
        lsp_rows = lsp.complete("%wait:")

    with patch(MODEL_CATALOG_PATCH, return_value=_model_entries()):
        ace_rows = _ace_clause_rows("%wait:")

    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert all(not row.insertion.endswith("=") for row in lsp_rows)


def test_ace_and_lsp_wait_prose_replacement_ranges_match(tmp_path: Path) -> None:
    text = "%wait:co and then do the thing"
    character = len("%wait:co")
    clause = classify_directive_completion(text, character)
    assert clause is not None
    assert (clause.start, clause.end) == (6, 8)

    with LspSession(tmp_path) as lsp:
        lsp_rows = lsp.complete(text, character=character)

    coder = next(row for row in lsp_rows if row.insertion == "coder")
    assert coder.raw is not None
    assert coder.raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": clause.start},
        "end": {"line": 0, "character": clause.end},
    }


def test_failure_degradation_retains_static_directive_rows(tmp_path: Path) -> None:
    helper = _write_failing_helper(tmp_path)

    with LspSession(tmp_path, helper=helper) as lsp:
        rows = lsp.complete("%wait(")

    assert [row.insertion for row in rows] == [
        "agent=",
        "bead=",
        "priority=",
        "proc=",
        "runners=",
        "time=",
        "unit=",
    ]


def test_lsp_uses_utf16_replacement_ranges(tmp_path: Path) -> None:
    with LspSession(tmp_path) as lsp:
        rows = lsp.complete("🙂 %mod")

    model = next(
        row for row in rows if row.label == "%model" and row.insertion == "%model"
    )
    assert model.label == "%model"
    assert model.insertion == "%model"

    raw = model.raw
    assert raw is not None
    assert raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": 3},
        "end": {"line": 0, "character": 7},
    }
