"""Tests for runtime and resource-backed completion candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.completion.candidates.protocol import Candidate
from sase.completion.candidates.providers import candidates_for


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    monkeypatch.delenv("SASE_SDD_BEADS_DIR", raising=False)
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)


def test_proc_candidates_list_ids_and_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    store = tmp_path / "sase-home" / "procs" / "procs.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path: (
                {
                    "schema_version": 3,
                    "procs": [
                        {
                            "proc_id": "abc123def456",
                            "label": "just check",
                            "status": "running",
                        }
                    ],
                }
                if name == "read_procs_snapshot"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("proc", "", project=None, limit=200)

    assert result == [Candidate("abc123def456", "running just check")]


def test_artifact_candidates_use_indexed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _filters: (
                [
                    {
                        "id": "explicit:0123456789abcdef01234567",
                        "label": "screenshot.png",
                    }
                ]
                if name == "artifact_files_query"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("artifact", "", project=None, limit=200)

    assert result == [Candidate("explicit:0123456789abcdef01234567", "screenshot.png")]


def test_artifact_ref_candidates_emit_canonical_file_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _filters: (
                [
                    {
                        "id": "explicit:0123456789abcdef01234567",
                        "label": "screenshot.png",
                    }
                ]
                if name == "artifact_files_query"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("artifact_ref", "", project=None, limit=200)

    assert result == [
        Candidate("file:explicit:0123456789abcdef01234567", "screenshot.png")
    ]


def test_patch_candidates_use_rust_parse_and_display_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.core.project_lifecycle_facade as project_lifecycle_facade
    import sase.core.rust as rust
    from sase.core.project_lifecycle_wire import (
        PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        ProjectRecordWire,
    )

    spec = tmp_path / "demo.sase"
    spec.write_bytes(b"NAME: alpha\n")
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="demo_key",
        project_dir=str(tmp_path),
        project_file=str(spec),
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Demo",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _data: (
                [
                    {
                        "name": "alpha",
                        "status": "InReview",
                        "project_display_name": "Demo",
                    }
                ]
                if name == "parse_patch_project_bytes"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("patch", "", project=None, limit=200)

    assert result == [Candidate("alpha", "InReview · Demo")]


def test_plan_candidates_emit_canonical_references(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.core.paths as core_paths
    import sase.core.rust as rust

    plans = tmp_path / "plans"
    month = plans / "202608"
    month.mkdir(parents=True)
    (month / "cli_completion.md").write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(core_paths, "sase_subdir", lambda name: plans)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda path, _roots: (
                f"plan:{Path(path).parent.name}/{Path(path).name}"
                if name == "plan_reference_canonicalize"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("plan", "", project=None, limit=200)

    assert result == [Candidate("plan:202608/cli_completion.md", "cli_completion")]


def _write_glossary_project(root: Path) -> None:
    config = root / "sase" / "sase.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "memory:\n"
        "  glossary:\n"
        "    Agent Hood:\n"
        "      definition: >-\n"
        "        An agent hood is a group of agents. It has a second sentence.\n"
        "      aliases:\n"
        "        - hood\n"
        "        - agent neighborhood\n"
        "    Stitch:\n"
        "      definition: A stitch is one recorded VCS change\n",
        encoding="utf-8",
    )


def test_glossary_candidates_use_slug_references_and_first_sentences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_glossary_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = candidates_for("glossary", "", project=None, limit=200)

    # Slug form: `sase glossary` resolves references case- and
    # separator-insensitively, so a hyphenated value never needs quoting.
    assert result == [
        Candidate("agent-hood", "An agent hood is a group of agents"),
        Candidate("hood", "alias of Agent Hood"),
        Candidate("agent-neighborhood", "alias of Agent Hood"),
        Candidate("stitch", "A stitch is one recorded VCS change"),
    ]


def test_glossary_candidates_filter_by_prefix_and_survive_missing_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    _write_glossary_project(project)
    monkeypatch.chdir(project)
    assert [
        candidate.value
        for candidate in candidates_for("glossary", "agent-", project=None, limit=200)
    ] == ["agent-hood", "agent-neighborhood"]

    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert candidates_for("glossary", "", project=None, limit=200) == []
