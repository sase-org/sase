"""CLI coverage for ``sase artifact pane show``."""

from __future__ import annotations

import json
from types import SimpleNamespace

from sase.ace.tui._artifact_link_contract import ARTIFACT_LINK_RELATIONS
from sase.ace.tui._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
)
from sase.ace.tui._artifact_tab_model import PaneCapability
from sase.artifact_cli.pane import handle_pane
from sase.main.parser import create_parser


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
    descriptors = assign_artifacts_digit_shortcuts(
        (
            fixed_descriptor("stitches"),
            fixed_descriptor("patches"),
            fixed_descriptor("beads"),
            fixed_descriptor("files"),
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
    assert payload["schema_version"] == 2
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
