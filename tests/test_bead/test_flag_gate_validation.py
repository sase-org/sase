"""FlagTriage trusted-kind validation against forged gate contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sase.bead.flag_gate import FLAG_TRIAGE_PREVIEW_PATH
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate

from .flag_gate_test_helpers import flag_triage_spec


def test_flag_triage_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = flag_triage_spec(request_id="flag-triage-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


def _preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == FLAG_TRIAGE_PREVIEW_PATH
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="extend OR remove OR keep OR close"),
            "invalid_flag_triage_query",
        ),
        (
            lambda spec: spec["options"][0].update(label="Ship it"),
            "invalid_flag_triage_options",
        ),
        (
            lambda spec: spec["options"][0]["inputs"][0].update(
                choices=["enabled", "disabled", "both"]
            ),
            "invalid_flag_triage_options",
        ),
        (
            lambda spec: spec["options"][1]["inputs"].pop(),
            "invalid_flag_triage_options",
        ),
        (
            lambda spec: spec["options"][2].update(feedback="optional"),
            "invalid_flag_triage_options",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(due_state="overdue"),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                flag={
                    "key": "Not Snake Case",
                    "remove_by_date": "2026-08-01",
                    "remove_by_release": "0.16.0",
                }
            ),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                definition={"kind": "sunset"},
            ),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(call_sites="not-a-list"),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                call_sites=[{"path": "a.py", "line": 1}]
            ),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                call_sites=[{"path": "a.py", "line": 0, "text": "x"}]
            ),
            "invalid_flag_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(due_as_of="2026-01-01"),
            "invalid_flag_triage_presentation",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_flag_triage_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_flag_triage_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_flag_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"]["chip"].update(glyph="?"),
            "invalid_flag_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_flag_triage_preview",
        ),
    ],
)
def test_flag_triage_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(flag_triage_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_flag_triage_kind_validation_accepts_blank_notes(gate_home: Path) -> None:
    del gate_home
    spec = flag_triage_spec(request_id="flag-triage-blank-notes", notes="")

    create_gate(spec)


def test_flag_triage_kind_validation_accepts_unregistered_definition(
    gate_home: Path,
) -> None:
    del gate_home
    spec = flag_triage_spec(request_id="flag-triage-unregistered", definition=None)

    create_gate(spec)


def test_flag_triage_kind_validation_rejects_preview_content_mismatch(
    gate_home: Path,
) -> None:
    del gate_home
    spec = deepcopy(flag_triage_spec(request_id="flag-triage-preview-mismatch"))
    preview_resource = _preview_resource(spec)
    preview_resource["content"] = preview_resource["content"].replace("sunset", "wip")

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_flag_triage_preview"


def test_flag_triage_kind_validation_rebuilds_preview_from_frozen_call_sites(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    from sase.bead.flag_gate import create_flag_triage_gate
    from sase.bead.flag_fields import FlagFields
    from sase.feature_flags.references import FlagCallSite
    from sase.notification_gates.hashing import load_and_verify_bundle

    source = tmp_path / "pkg"
    source.mkdir()
    (source / "demo.py").write_text(
        "from sase.feature_flags import FeatureFlag\nFeatureFlag.demo_flag\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.feature_flags.references._sase_package_root", lambda: source
    )
    frozen = (FlagCallSite(path="demo.py", line=2, text="FeatureFlag.demo_flag"),)
    gate = create_flag_triage_gate(
        request_id="flag-triage-frozen-sites",
        bead_id="sase-flag.1",
        project="sase",
        title="Remove the demo_flag flag",
        flag=FlagFields(
            key="demo_flag",
            kind="beta",
            remove_by_date="2026-08-01",
            remove_by_release="0.16.0",
        ),
        due_state="due",
        due_as_of="2026-08-16",
        release="0.16.0",
        call_sites=frozen,
    )
    (source / "demo.py").write_text(
        "from sase.feature_flags import FeatureFlag\nFeatureFlag.other_flag\n",
        encoding="utf-8",
    )

    load_and_verify_bundle(gate.bundle_path)
    preview = (gate.bundle_path / "flag.md").read_text(encoding="utf-8")
    assert "`demo.py:2`" in preview
    assert "FeatureFlag.demo_flag" in preview
    assert "FeatureFlag.other_flag" not in preview
