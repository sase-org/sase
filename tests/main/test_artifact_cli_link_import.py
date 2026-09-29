"""Tests for ``sase artifact link import-indexes`` and ``migrate-notes``.

Split from ``test_artifact_cli_link``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from sase.artifact_cli.link_import import handle_link_import_indexes
from sase.artifact_cli.link_migrate import handle_link_migrate_notes


def test_import_indexes_apply_requires_matching_attestation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = object()
    report = SimpleNamespace(
        plan=SimpleNamespace(fenced_marker=marker),
        to_json_dict=lambda: {
            "applied": False,
            "plan": {"project_key": "gh_sase-org__sase"},
        },
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        "sase.artifact_cli.link_import.resolve_artifact_link_store",
        lambda *, cwd: SimpleNamespace(project_key="gh_sase-org__sase"),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_import.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: object(),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_import.artifact_link_cutover_attestation",
        lambda _marker: "fleet-capable-goodtoken",
    )

    def _fake_import(_store: object, *, apply: bool) -> object:
        calls.append(apply)
        return report

    monkeypatch.setattr(
        "sase.artifact_cli.link_import.import_artifact_link_indexes",
        _fake_import,
    )

    rc = handle_link_import_indexes(
        argparse.Namespace(apply=True, attestation="wrong-token", json=True)
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert calls == [False]
    assert json.loads(captured.out)["applied"] is False
    assert "fleet-capable-goodtoken" in captured.err


def test_migrate_notes_apply_and_dry_run_succeed(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _View:
        def __enter__(self) -> _View:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def list_issues(self) -> tuple[object, ...]:
            return ()

    class _Mutation:
        project = SimpleNamespace(mutation_changed=False)

        def __enter__(self) -> _Mutation:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def commit(self, _message: str) -> None:
            raise AssertionError("empty migration should not commit")

    monkeypatch.setattr("sase.bead.cli_common.get_read_view", lambda: _View())
    monkeypatch.setattr("sase.bead.cli_common.bead_store_mutation", lambda: _Mutation())
    assert handle_link_migrate_notes(argparse.Namespace(apply=True, json=False)) == 0
    assert "RELATED: migration (applied)" in capsys.readouterr().out
    assert handle_link_migrate_notes(argparse.Namespace(apply=False, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["converted"] == []
    assert payload["worklist"] == []
