"""Tests for ``sase artifact link add/list/rm``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_cli.link_migrate import handle_link_migrate_notes
from sase.artifact_cli.link_ops import handle_link_add, handle_link_list, handle_link_rm
from sase.artifact_cli.link_relations import (
    handle_link_relation,
    handle_link_relation_list,
    handle_link_relation_show,
)
from sase.main.parser import create_parser
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: ArtifactLinkStore) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-08-18T23:40:00Z",
    )


def test_add_list_rm_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_store(monkeypatch, store)
    add_args = argparse.Namespace(
        source_ref="@plan:202608/a.md",
        relation="implements",
        target_ref="plan:202608/b.md",
        why="extends the ref contract this epic landed",
    )
    assert handle_link_add(add_args) == 0
    first = capsys.readouterr().out
    assert "added" in first
    assert handle_link_add(add_args) == 0
    second = capsys.readouterr().out
    assert "unchanged" in second
    assert (
        handle_link_list(
            argparse.Namespace(
                reference="plan:202608/a.md",
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
    assert len(payload) == 1
    assert payload[0]["relation"] == "implements"
    assert (
        handle_link_rm(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                target_ref="plan:202608/b.md",
                relation=None,
            )
        )
        == 0
    )
    assert "removed implements" in capsys.readouterr().out
    assert store.load_artifact_rows("plan:202608/a.md") == ()


def test_add_and_rm_work_without_feature_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_store(monkeypatch, store)
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                relation="related",
                target_ref="plan:202608/b.md",
                why="shares a root cause",
            )
        )
        == 0
    )
    assert (
        handle_link_rm(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                target_ref="plan:202608/b.md",
                relation=None,
            )
        )
        == 0
    )
    assert capsys.readouterr().err == ""


def test_list_reads_rows_without_feature_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_store(monkeypatch, store)
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


def test_add_rejects_reserved_and_machine_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_store(monkeypatch, store)
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="bead:sase-a",
                relation="blocks",
                target_ref="bead:sase-b",
                why="ordering",
            )
        )
        == 1
    )
    assert "sase bead dep" in capsys.readouterr().err
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="agent:one",
                relation="cites",
                target_ref="plan:202608/a.md",
                why="from a prompt",
            )
        )
        == 1
    )
    assert "prompt-ref" in capsys.readouterr().err


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


def test_relation_show_prints_direction_and_examples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_link_relation_show(argparse.Namespace(slug="implements")) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "implemented-by" in output
    assert "plan is the source, the bead is the target" in output
    assert "plan:" in output and "implements bead:" in output
    assert "bead:" in output and "implements plan:" in output
    assert "Recommended source kinds: plan" in output
    assert "Recommended target kinds: bead" in output


def test_relation_show_json_emits_full_registry_entry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        handle_link_relation_show(argparse.Namespace(slug="implements", json=True)) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["slug"] == "implements"
    assert payload["inverse"] == "implemented-by"
    assert payload["direction_note"]
    assert payload["positive_example"]
    assert payload["negative_example"]
    assert payload["recommended_source_kinds"] == ["plan"]
    assert payload["recommended_target_kinds"] == ["bead"]


def test_relation_show_unknown_slug_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_link_relation_show(argparse.Namespace(slug="bogus")) == 1
    assert "unknown relation" in capsys.readouterr().err


def test_relation_list_covers_every_builtin_slug(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_link_relation_list(argparse.Namespace(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    slugs = {item["slug"] for item in payload}
    assert slugs == {
        "cites",
        "read",
        "related",
        "supersedes",
        "implements",
        "derives-from",
    }


def test_relation_dispatch_defaults_to_usage_without_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_link_relation(argparse.Namespace()) == 2
    assert "relation {list,show}" in capsys.readouterr().err


def test_parser_link_relation_show_uses_positional() -> None:
    args = create_parser().parse_args(
        ["artifact", "link", "relation", "show", "implements"]
    )
    assert args.link_subcommand == "relation"
    assert args.relation_subcommand == "show"
    assert args.slug == "implements"


def test_parser_link_relation_bare_defaults_to_list() -> None:
    args = create_parser().parse_args(["artifact", "link", "relation"])
    assert args.link_subcommand == "relation"
    assert args.relation_subcommand == "list"


def test_parser_link_add_uses_positionals() -> None:
    args = create_parser().parse_args(
        [
            "artifact",
            "link",
            "add",
            "plan:a.md",
            "related",
            "plan:b.md",
            "shares a root cause",
        ]
    )
    assert args.link_subcommand == "add"
    assert args.source_ref == "plan:a.md"
    assert args.relation == "related"
    assert args.target_ref == "plan:b.md"
    assert args.why == "shares a root cause"
