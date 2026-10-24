"""CLI coverage for ``sase artifact pane show``."""

from __future__ import annotations

import json
from types import SimpleNamespace

from sase.ace.tui._artifact_link_contract import ARTIFACT_LINK_RELATIONS
from sase.ace.tui._artifact_tab_descriptors import (
    _assign_artifacts_digit_shortcuts,
    _fixed_descriptor,
)
from sase.ace.tui._artifact_tab_model import (
    ARTIFACTS_FILES_PANE_DISABLED_HINT,
    PaneCapability,
)
from sase.artifact_cli.pane import handle_pane
from sase.main.parser import create_parser
from sase.feature_flags import override_flags


def _artifact_link_relation_names() -> list[str]:
    return [item.name for item in ARTIFACT_LINK_RELATIONS]


def test_parser_accepts_pane_show_json() -> None:
    args = create_parser().parse_args(["artifact", "pane", "show", "stitches", "-j"])
    assert args.artifact_subcommand == "pane"
    assert args.pane_subcommand == "show"
    assert args.pane_id == "stitches"
    assert args.json is True


def test_pane_show_json_explains_verdicts(
    monkeypatch,
    capsys,
) -> None:
    descriptors = _assign_artifacts_digit_shortcuts(
        (
            _fixed_descriptor("agents"),
            _fixed_descriptor("stitches"),
            _fixed_descriptor("patches"),
            _fixed_descriptor("beads"),
            _fixed_descriptor("files"),
        )
    )
    monkeypatch.setattr(
        "sase.artifact_cli.pane.artifacts_pane_contract",
        lambda pane_id: next(
            (item.contract for item in descriptors if item.id == pane_id),
            None,
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.pane.configured_artifacts_pane_ids",
        lambda: tuple(item.id for item in descriptors),
    )
    exit_code = handle_pane(
        SimpleNamespace(pane_subcommand="show", pane_id="beads", json=True)
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["id"] == "beads"
    assert payload["schema_version"] == 3
    assert payload["description_detail"]["summary"] == payload["description"]
    assert payload["description_detail"]["body"]
    assert payload["description_detail"]["summary_source"] == "builtin"
    assert payload["description_detail"]["body_source"] == "builtin"
    names = [item["capability"] for item in payload["capabilities"]]
    assert names == [item.value for item in PaneCapability]
    by_name = {item["capability"]: item for item in payload["capabilities"]}
    assert by_name["mutation"]["state"] == "ON"
    assert by_name["versions"]["state"] == "OFF"
    assert by_name["relations"]["state"] == "ON"
    assert by_name["shell"]["state"] == "ON"
    assert by_name["status_counters"]["state"] == "ON"
    assert by_name["shell"]["rule"] == "shell_from_host"
    assert by_name["status_counters"]["rule"] == "status_counters_from_declaration"
    # Beads never had real grouping modes; sase-m6.9 corrected its previously
    # false GROUPING capability declaration to OFF with no modes.
    assert by_name["grouping"]["state"] == "OFF"
    assert [item["name"] for item in payload["relations"]] == [
        "parent",
        "children",
        "plans",
        "dependencies",
        *_artifact_link_relation_names(),
    ]
    assert payload["grouping"]["default_mode"] is None
    assert payload["grouping"]["modes"] == []
    key_actions = {item["action"] for item in payload["keys"]}
    assert "beads_next" in key_actions
    assert "refresh" in key_actions
    assert "plans_next" not in key_actions


def test_pane_show_text_prints_description(monkeypatch, capsys) -> None:
    descriptor = _fixed_descriptor("stitches")
    monkeypatch.setattr(
        "sase.artifact_cli.pane.artifacts_pane_contract",
        lambda pane_id: descriptor.contract if pane_id == descriptor.id else None,
    )
    exit_code = handle_pane(
        SimpleNamespace(pane_subcommand="show", pane_id="stitches", json=False)
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Description" in out
    assert " ".join(descriptor.description.split()) in " ".join(out.split())
    assert "summary source: builtin" in out
    assert "body source: builtin" in out


def test_pane_show_unknown_id_lists_configured(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.pane.artifacts_pane_contract", lambda _id: None
    )
    monkeypatch.setattr(
        "sase.artifact_cli.pane.configured_artifacts_pane_ids",
        lambda: ("beads", "files", "patches", "stitches"),
    )
    exit_code = handle_pane(
        SimpleNamespace(pane_subcommand="show", pane_id="missing", json=False)
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "unknown Artifacts pane 'missing'" in err
    assert "beads" in err
    assert "stitches" in err


def test_pane_show_files_reports_disabled_beta_in_text_and_json(capsys) -> None:
    with override_flags(artifacts_files_pane=False):
        text_code = handle_pane(
            SimpleNamespace(pane_subcommand="show", pane_id="files", json=False)
        )
        text = capsys.readouterr().out
        json_code = handle_pane(
            SimpleNamespace(pane_subcommand="show", pane_id="files", json=True)
        )
        payload = json.loads(capsys.readouterr().out)

    assert text_code == json_code == 0
    assert "Artifacts ▸ Files beta pane is disabled" in text
    assert " ".join(ARTIFACTS_FILES_PANE_DISABLED_HINT.split()) in " ".join(
        text.split()
    )
    assert payload == {
        "schema_version": 3,
        "pane": "files",
        "disabled": True,
        "feature_flag": "artifacts_files_pane",
        "summary": "Artifacts ▸ Files is a beta pane that is off by default.",
        "hint": ARTIFACTS_FILES_PANE_DISABLED_HINT,
    }


def test_pane_show_files_keeps_normal_contract_when_enabled(capsys) -> None:
    with override_flags(artifacts_files_pane=True):
        code = handle_pane(
            SimpleNamespace(pane_subcommand="show", pane_id="files", json=True)
        )
        payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["schema_version"] == 3
    assert payload["id"] == "files"
    assert "disabled" not in payload
