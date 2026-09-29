"""Tests for ``sase artifact link list``.

Split from ``test_artifact_cli_link``; shared helpers live in
``_artifact_cli_link_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.link_ops import handle_link_add, handle_link_list
from tests.main._artifact_cli_link_helpers import (
    make_store,
    patch_link_ops_store,
)


def test_list_reads_rows_without_feature_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    handle_link_add(
        argparse.Namespace(
            source_ref="plan:202608/a.md",
            relation="related",
            target_ref="plan:202608/b.md",
            why="shares a root cause",
        )
    )
    capsys.readouterr()
    assert (
        handle_link_list(
            argparse.Namespace(
                reference=None,
                direction="both",
                json=True,
                limit=50,
                origin=None,
                relation=None,
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["relation"] == "related"


def test_list_without_reference_merges_in_projected_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    projected_row = {
        "schema_version": 2,
        "source_ref": "stitch:sase@0123456789abcdef0123456789abcdef01234567",
        "relation": "implements",
        "target_ref": "bead:sase-xx",
        "description": "commit trailer names bead sase-xx",
        "origin": "projected",
        "created_by": "projection:stitch-bead",
        "created_at": "2026-08-20T00:00:00Z",
        "uses": 1,
    }
    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_projected.project_link_rows",
        lambda _inputs: (projected_row,),
    )
    handle_link_add(
        argparse.Namespace(
            source_ref="plan:202608/a.md",
            relation="related",
            target_ref="plan:202608/b.md",
            why="shares a root cause",
        )
    )
    capsys.readouterr()
    assert (
        handle_link_list(
            argparse.Namespace(
                reference=None,
                direction="both",
                json=True,
                limit=50,
                origin="projected",
                relation=None,
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["created_by"] == "projection:stitch-bead"
    assert (
        handle_link_list(
            argparse.Namespace(
                reference=None,
                direction="both",
                json=True,
                limit=50,
                origin="manual",
                relation=None,
            )
        )
        == 0
    )
    manual_payload = json.loads(capsys.readouterr().out)
    assert len(manual_payload) == 1
    assert manual_payload[0]["relation"] == "related"


def test_list_source_store_reads_durable_rows_when_index_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    store.upsert_row(
        {
            "schema_version": 2,
            "source_ref": "agent:pending.athena.worker",
            "relation": "cites",
            "target_ref": "plan:202608/a.md",
            "description": "prompt citation",
            "origin": "prompt_ref",
            "created_by": "agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        }
    )
    capsys.readouterr()
    store._write_aggregate({"rows": []})  # noqa: SLF001 - simulate stale index

    assert (
        handle_link_list(
            argparse.Namespace(
                reference=None,
                direction="both",
                json=True,
                limit=50,
                origin=None,
                relation=None,
                source="index",
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []

    assert (
        handle_link_list(
            argparse.Namespace(
                reference=None,
                direction="both",
                json=True,
                limit=50,
                origin=None,
                relation=None,
                source="store",
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["relation"] == "cites"
