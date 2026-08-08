"""Run the shared gate fixture set through every answering surface.

See :mod:`tests.gate_conformance` for why this matrix exists. Note that the
CLI driver submits per-option values as whole JSON documents
(``--option-input``); ``--set``'s per-field typing is covered directly in
``tests/test_gate_cli_answer.py`` rather than here, so a matrix pass never
implies the coercion layer was exercised.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.service import create_gate
from tests.gate_conformance._cases import CASE_BUILDERS, ConformanceCase
from tests.gate_conformance._surfaces import (
    PENDING_CAPABILITY_PHASES,
    SURFACES,
    Surface,
    SurfaceTarget,
)

#: A bead id, which a skip reason must never be, since the bead closes and the
#: reason does not.
_BEAD_ID = re.compile(r"\bsase-[a-z]?\d+(\.\d+)+\b")


@pytest.mark.parametrize("case_id", sorted(CASE_BUILDERS))
@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.name)
def test_gate_conformance(
    case_id: str,
    surface: Surface,
    gate_home: Path,
    tmp_path: Path,
) -> None:
    """One case, one surface: the same gate must behave the same way."""
    del gate_home
    case = CASE_BUILDERS[case_id](tmp_path)
    missing = surface.missing(case.requires)
    if missing:
        reasons = ", ".join(
            f"{capability} ({surface.why_missing(capability)})"
            for capability in sorted(missing)
        )
        pytest.skip(f"{surface.name} cannot submit: {reasons}")

    creation = create_gate(case.spec)
    target = SurfaceTarget(
        bundle_path=creation.bundle_path,
        kind=creation.kind,
        request_id=creation.request_id,
        notification_id=creation.notification_id,
    )
    for prior in case.prior:
        surface.submit(target, prior)
    if case.cancel_before_submit:
        cancel_gate(creation.bundle_path, source="conformance")

    outcome = surface.submit(target, case.submission)

    if not case.answered:
        _assert_rejected(case, outcome.message, creation.bundle_path)
        return
    assert outcome.answered, outcome.message
    _assert_answered(case, creation.response_path)


def _assert_answered(case: ConformanceCase, response_path: Path) -> None:
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == list(case.submission.selected)
    if case.expected_feedback is not None:
        assert response["feedback"] == case.expected_feedback

    results = {entry["id"]: entry["result"] for entry in response["option_results"]}
    for option_id, expected in case.expected_results.items():
        actual = results[option_id]
        assert isinstance(actual, dict), actual
        for key, value in expected.items():
            assert actual.get(key) == value, (option_id, key, actual)

    for option_id, expected_input in case.expected_response_inputs.items():
        assert response["option_inputs"][option_id] == expected_input


def _assert_rejected(case: ConformanceCase, message: str, bundle_path: Path) -> None:
    assert not (bundle_path / "response.json").exists(), (
        "a rejected submission must leave the gate answerable"
    )
    if case.expected_error_text:
        assert any(text in message for text in case.expected_error_text), message
    if case.expected_error_code is not None:
        assert case.expected_error_code in _recorded_error_codes(bundle_path), (
            "every rejection must be diagnosable under errors/"
        )


def test_every_surface_gap_states_why_it_cannot_submit() -> None:
    """A skipped case must name the limitation, not a bead that will close.

    The mobile leg spent this epic skipping ten cases against three entries
    that all named an already-closed phase, so the coverage they deferred was
    never collected. A gap has to explain itself, and an entry has to vanish
    when the surface grows the capability.
    """
    declared = {
        capability for surface in SURFACES for capability in surface.capabilities
    }
    surfaces = {surface.name: surface for surface in SURFACES}

    for (surface_name, capability), reason in PENDING_CAPABILITY_PHASES.items():
        surface = surfaces[surface_name]
        assert capability in declared, (
            f"{surface_name} defers an unknown capability {capability!r}"
        )
        assert capability not in surface.capabilities, (
            f"{surface_name} declares {capability!r}; drop its stale excuse"
        )
        assert not _BEAD_ID.search(reason), (
            f"{surface_name}/{capability} defers to a bead: {reason!r}"
        )

    for surface in SURFACES:
        for capability in sorted(surface.missing(frozenset(declared))):
            assert (surface.name, capability) in PENDING_CAPABILITY_PHASES, (
                f"{surface.name} cannot submit {capability!r} and says nothing"
            )


def _recorded_error_codes(bundle_path: Path) -> set[str]:
    errors = bundle_path / "errors"
    if not errors.is_dir():
        return set()
    codes: set[str] = set()
    for path in errors.glob("*.json"):
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("code"), str):
            codes.add(payload["code"])
    return codes
