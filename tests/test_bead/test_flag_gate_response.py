"""Trusted FlagTriage response translation coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead._flag_gate_response import (
    FlagTriageResponse,
    translate_flag_triage_response,
)
from sase.bead._flag_gate_spec import FlagTriageAction
from sase.bead.model import FlagRecord
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.flag_gate_test_helpers import flag_triage_spec
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def _option_result(action: FlagTriageAction) -> dict[str, str]:
    if action == "remove":
        return {"action": action, "winner": "enabled"}
    if action == "extend":
        return {
            "action": action,
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.17.0",
        }
    return {"action": action}


def _response(
    action: FlagTriageAction,
    *,
    result: dict[str, str] | None = None,
    feedback: str | None = None,
    source: str = "tui",
    **overrides: Any,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "selected_option_ids": [action],
        "option_results": [{"id": action, "result": result or _option_result(action)}],
        "source": source,
    }
    if feedback is not None:
        response["feedback"] = feedback
    response.update(overrides)
    return response


@pytest.mark.parametrize(
    ("action", "feedback"),
    [
        ("remove", None),
        ("extend", "Needs another release cycle."),
        ("keep", "This should become an ops setting."),
        ("close", "The flag never shipped."),
    ],
)
def test_flag_triage_translation_round_trips_each_action(
    gate_home: Path,
    action: FlagTriageAction,
    feedback: str | None,
) -> None:
    del gate_home
    gate = create_gate(flag_triage_spec(request_id=f"flag-triage-translate-{action}"))

    translated = translate_flag_triage_response(
        gate.bundle_path,
        _response(action, feedback=feedback, source="mobile"),
    )

    assert translated == FlagTriageResponse(
        bead_id="sase-flag.1",
        project="sase",
        title="Remove the prettier_enabled flag",
        key="prettier_enabled",
        old_remove_by_date="2026-08-01",
        old_remove_by_release="0.16.0",
        action=action,
        feedback=feedback,
        source="mobile",
        winner="enabled" if action == "remove" else None,
        remove_by_date="2026-12-01" if action == "extend" else None,
        remove_by_release="0.17.0" if action == "extend" else None,
    )


def test_flag_triage_translation_trusts_request_identity_and_current_thresholds(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(
        flag_triage_spec(
            request_id="flag-triage-trusted-request",
            bead_id="sase-flag.actual",
            project="sase",
            title="Trusted flag bead title",
            flag=FlagRecord(
                key="actual_flag",
                remove_by_date="2026-09-01",
                remove_by_release="0.18.0",
            ),
        )
    )

    translated = translate_flag_triage_response(
        gate.bundle_path,
        _response(
            "extend",
            feedback="Current thresholds should move.",
            bead_id="sase-flag.forged",
            project="other-project",
            title="Forged title",
            key="forged_flag",
            old_remove_by_date="1999-01-01",
            old_remove_by_release="0.0.1",
            flag={
                "key": "forged_flag",
                "remove_by_date": "1999-01-01",
                "remove_by_release": "0.0.1",
            },
        ),
    )

    assert translated.bead_id == "sase-flag.actual"
    assert translated.project == "sase"
    assert translated.title == "Trusted flag bead title"
    assert translated.key == "actual_flag"
    assert translated.old_remove_by_date == "2026-09-01"
    assert translated.old_remove_by_release == "0.18.0"


def test_flag_triage_translation_rejects_non_flag_triage_bundle(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="flag-triage-task-bundle"))

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(gate.bundle_path, _response("remove"))

    assert exc_info.value.code == "invalid_response"
    assert "not a flag triage gate" in str(exc_info.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"selected_option_ids": None},
        {"selected_option_ids": []},
        {"selected_option_ids": ["remove", "keep"]},
        {"selected_option_ids": ["launch"]},
        {"option_results": None},
        {"option_results": [{"id": "remove", "result": {"action": "extend"}}]},
    ],
)
def test_flag_triage_translation_rejects_malformed_response(
    gate_home: Path,
    overrides: dict[str, Any],
) -> None:
    del gate_home
    gate = create_gate(
        flag_triage_spec(
            request_id=f"flag-triage-malformed-{len(json.dumps(overrides))}"
        )
    )

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(
            gate.bundle_path,
            _response("remove", **overrides),
        )

    assert exc_info.value.code == "invalid_response"


@pytest.mark.parametrize("action", ["extend", "keep", "close"])
def test_flag_triage_translation_rejects_missing_required_feedback(
    gate_home: Path,
    action: FlagTriageAction,
) -> None:
    del gate_home
    gate = create_gate(flag_triage_spec(request_id=f"flag-triage-no-feedback-{action}"))

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(
            gate.bundle_path,
            _response(action, feedback=" "),
        )

    assert exc_info.value.code == "invalid_response"
    assert "requires a reason" in str(exc_info.value)


def test_flag_triage_translation_rejects_remove_without_winning_branch(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(flag_triage_spec(request_id="flag-triage-remove-no-winner"))

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(
            gate.bundle_path,
            _response("remove", result={"action": "remove"}),
        )

    assert exc_info.value.code == "invalid_response"
    assert "requires a winning branch" in str(exc_info.value)


def test_flag_triage_translation_rejects_extend_without_new_thresholds(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(flag_triage_spec(request_id="flag-triage-extend-no-thresholds"))

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(
            gate.bundle_path,
            _response(
                "extend",
                result={"action": "extend", "remove_by_date": "2026-12-01"},
                feedback="Needs another release cycle.",
            ),
        )

    assert exc_info.value.code == "invalid_response"
    assert "requires new thresholds" in str(exc_info.value)


@pytest.mark.parametrize(
    ("field_path", "code"),
    [
        (("payload", "bead_id"), "invalid_flag_payload"),
        (("payload", "flag", "key"), "invalid_flag_payload"),
    ],
)
def test_flag_triage_translation_rejects_malformed_persisted_payload(
    gate_home: Path,
    field_path: tuple[str, ...],
    code: str,
) -> None:
    del gate_home
    gate = create_gate(flag_triage_spec(request_id=f"flag-triage-bad-{field_path[-1]}"))
    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    cursor: dict[str, Any] = request
    for field in field_path[:-1]:
        cursor = cursor[field]
    cursor[field_path[-1]] = ""
    gate.request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(GateError) as exc_info:
        translate_flag_triage_response(gate.bundle_path, _response("remove"))

    assert exc_info.value.code == code
