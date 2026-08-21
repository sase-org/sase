from __future__ import annotations

import argparse
import io
import json
from unittest.mock import patch

import pytest

from sase.finalizers.catalog import (
    _FinalizerCatalogBuild,
    _FinalizerCatalogEntry,
)
from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser


def _ok_catalog() -> _FinalizerCatalogBuild:
    return _FinalizerCatalogBuild(
        status="ok",
        entries=(
            _FinalizerCatalogEntry(
                value="commit",
                provider_ref="builtin@commit",
                required=True,
                is_default=True,
                max_attempts=2,
                documentation="Required for this launch.",
                provenance_id="default",
            ),
            _FinalizerCatalogEntry(
                value="lint",
                provider_ref="builtin@command",
                is_default=True,
                after=("format",),
                max_attempts=2,
                documentation="Selected by default.",
            ),
        ),
    )


def test_parser_accepts_editor_helper_bridge_finalizer_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "finalizer-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "finalizer-catalog"


def test_finalizer_catalog_help_describes_request_and_fail_closed_envelope() -> None:
    stdout = io.StringIO()
    parser = create_parser()
    with pytest.raises(SystemExit) as exc, patch("sys.stdout", stdout):
        parser.parse_args(["editor", "helper-bridge", "finalizer-catalog", "-h"])

    help_text = stdout.getvalue()
    assert exc.value.code == 0
    assert "schema_version" in help_text
    assert "status=error" in help_text
    assert "provider" in help_text
    assert "%final" in help_text


def test_editor_helper_bridge_finalizer_catalog_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations._editor_helper_finalizers.build_finalizer_completion_catalog",
        _ok_catalog,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="finalizer-catalog"),
        stdin=io.StringIO(
            json.dumps(
                {
                    "schema_version": 1,
                    "project": "sase",
                    "unknown_client_field": True,
                }
            )
        ),
        stdout=stdout,
        stderr=stderr,
    )

    payload = stdout.getvalue()
    data = json.loads(payload)
    assert code == 0
    assert stderr.getvalue() == ""
    assert " :" not in payload
    assert data["schema_version"] == 1
    assert data["status"] == "ok"
    assert data["entries"][0]["value"] == "commit"
    assert data["entries"][0]["required"] is True
    assert data["entries"][1]["after"] == ["format"]


def test_editor_helper_bridge_finalizer_catalog_accepts_schema_only_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations._editor_helper_finalizers.build_finalizer_completion_catalog",
        _ok_catalog,
    )
    stdout = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="finalizer-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "ok"


def test_editor_helper_bridge_finalizer_catalog_rejects_wrong_schema_version() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="finalizer-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 2})),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert "unsupported finalizer-catalog schema_version" in stderr.getvalue()


def test_editor_helper_bridge_finalizer_catalog_fail_closed_on_malformed_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations._editor_helper_finalizers.build_finalizer_completion_catalog",
        lambda: _FinalizerCatalogBuild(
            status="error",
            message="finalizers must be a mapping",
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="finalizer-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["status"] == "error"
    assert data["entries"] == []
    assert "mapping" in data["message"]
