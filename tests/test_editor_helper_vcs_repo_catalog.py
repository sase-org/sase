from __future__ import annotations

import argparse
import io
import json

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser


def test_parser_accepts_editor_helper_bridge_vcs_repo_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "vcs-repo-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "vcs-repo-catalog"


def test_editor_helper_bridge_vcs_repo_catalog_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.editor_helpers.vcs_repo_catalog_response",
        lambda request: {
            "schema_version": 1,
            "status": "ok",
            "error_kind": None,
            "message": "",
            "provider_display": "GitHub",
            "stale": False,
            "entries": [
                {
                    "name": "sase",
                    "ref": "bbugyi200/sase",
                    "description": "",
                    "visibility": "PUBLIC",
                    "is_fork": False,
                    "is_archived": False,
                    "pushed_at": None,
                }
            ],
            "request_echo": request,
        },
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="vcs-repo-catalog"),
        stdin=io.StringIO(
            json.dumps(
                {
                    "schema_version": 1,
                    "workflow": "gh",
                    "namespace": "bbugyi200",
                }
            )
        ),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["request_echo"] == {
        "schema_version": 1,
        "workflow": "gh",
        "namespace": "bbugyi200",
    }
    assert data["entries"][0]["ref"] == "bbugyi200/sase"


def test_editor_helper_bridge_vcs_repo_catalog_reports_bad_request() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="vcs-repo-catalog"),
        stdin=io.StringIO(
            json.dumps(
                {
                    "schema_version": 1,
                    "namespace": "bbugyi200",
                }
            )
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("editor helper bridge error:")
