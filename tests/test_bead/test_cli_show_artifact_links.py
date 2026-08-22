"""Public ``sase bead show`` coverage for typed artifact-link neighborhoods."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from tests._conftest_environment import redirect_sase_home
from tests.main.parser_help_helpers import parser_for
from tests.test_bead.cli_show_style_test_helpers import strip_sgr


def _row(
    source: str,
    relation: str,
    target: str,
    *,
    origin: str = "manual",
    description: str = "lands the approved CLI design",
    created_by: str = "alice.athena.worker",
    created_at: str = "2026-08-22T14:10:00Z",
    uses: int = 1,
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": description,
        "origin": origin,
        "created_by": created_by,
        "created_at": created_at,
        "uses": uses,
    }


def _install_show(
    monkeypatch: pytest.MonkeyPatch,
    project: BeadProject,
    store: ArtifactLinkStore | None,
) -> list[str]:
    opened: list[str] = []

    @contextmanager
    def read_view() -> Iterator[BeadProject]:
        yield project

    def resolve_store() -> ArtifactLinkStore:
        opened.append("store")
        assert store is not None
        return store

    monkeypatch.setattr("sase.bead.cli_query.get_read_view", read_view)
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: False,
    )
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url", lambda _name: None
    )
    monkeypatch.setattr(
        "sase.bead.cli_detail_links.resolve_artifact_link_store",
        resolve_store,
    )
    return opened


def _show(issue_id: str, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    args = create_parser().parse_args(["bead", "show", issue_id, *flags])
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def _show_err(
    issue_id: str, capsys: pytest.CaptureFixture[str], *flags: str
) -> tuple[str, str, int]:
    args = create_parser().parse_args(["bead", "show", issue_id, *flags])
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)
    captured = capsys.readouterr()
    return captured.out, captured.err, int(excinfo.value.code)


def test_show_mixed_neighborhood_and_json_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        opened = _install_show(monkeypatch, project, store)
        store.upsert_row(
            _row(
                f"bead:{left.id}",
                "implements",
                "plan:202608/link-aware-bead-show.md",
                description="Lands the approved CLI design.",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{right.id}",
                "implements",
                f"bead:{left.id}",
                description="Right implements left.",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{left.id}",
                "related",
                f"bead:{right.id}",
                origin="migrated",
                description="Shares the same rendering contract.",
                created_by="alice",
                created_at="2026-08-20T09:00:00Z",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{left.id}",
                "supersedes",
                "plan:202607/old.md",
                description="Replaces the older plan.",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{right.id}",
                "supersedes",
                f"bead:{left.id}",
                description="Right supersedes left.",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{left.id}",
                "derives-from",
                "research:202608/source.md",
                description="Uses its measurements.",
            )
        )
        store.upsert_row(
            _row(
                f"bead:{right.id}",
                "derives-from",
                f"bead:{left.id}",
                description="Right derives from left.",
            )
        )
        store.upsert_row(
            _row(
                "agent:alice.athena.reviewer",
                "cites",
                f"bead:{left.id}",
                origin="prompt_ref",
                description="Prompt citation of the bead.",
                created_by="alice.athena.reviewer",
                created_at="2026-08-22T15:00:00Z",
                uses=3,
            )
        )
        store.upsert_row(
            _row(
                "agent:alice.athena.reviewer",
                "read",
                f"bead:{left.id}",
                origin="read",
                description="Audited read of the bead.",
                created_by="alice.athena.reviewer",
                created_at="2026-08-22T16:00:00Z",
                uses=2,
            )
        )
        store.upsert_row(
            _row(
                "plan:202608/sidecar.md",
                "related",
                f"bead:{left.id}",
                description="Sidecar document related to the bead.",
            )
        )

        out = _show(left.id, capsys)
        assert "DEPENDS ON" not in out
        assert "LINKS (" in out
        assert "→ implements · plan:202608/link-aware-bead-show.md" in out
        assert "← implemented-by · " in out
        assert "↔ related · " in out
        assert "→ supersedes · plan:202607/old.md" in out
        assert "← superseded-by · " in out
        assert "→ derives-from · research:202608/source.md" in out
        assert "← derived-into · " in out
        assert "REFERENCED BY (" in out
        assert "← cited-by · agent:alice.athena.reviewer" in out
        assert "prompt citation · 3 uses · added 2026-08-22T15:00:00Z" in out
        assert "← read-by · agent:alice.athena.reviewer" in out
        assert "audited read · 2 uses" in out
        assert opened == ["store"]

        payload = json.loads(_show(left.id, capsys, "--format", "json"))
        assert "artifact_links" in payload
        assert payload["issue"]["links"]
        keys = list(payload["artifact_links"][0])
        assert keys == [
            "source_ref",
            "target_ref",
            "relation",
            "displayed_relation",
            "direction",
            "counterpart_ref",
            "reason",
            "origin",
            "actor",
            "timestamp",
            "uses",
        ]
        cited = next(
            row
            for row in payload["artifact_links"]
            if row["displayed_relation"] == "cited-by"
        )
        assert cited["direction"] == "incoming"
        assert cited["uses"] == 3
        assert cited["relation"] == "cites"


def test_show_no_links_omits_sections_and_never_opens_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        opened = _install_show(monkeypatch, project, store)
        store.upsert_row(
            _row(
                f"bead:{issue.id}",
                "implements",
                "plan:202608/a.md",
            )
        )

        full = _show(issue.id, capsys, "--no-links")
        json_payload = json.loads(
            _show(issue.id, capsys, "--format", "json", "--no-links")
        )
        compact = _show(issue.id, capsys, "--format", "compact")
        compact_flag = _show(issue.id, capsys, "--format", "compact", "--no-links")

    assert "LINKS" not in full
    assert "REFERENCED BY" not in full
    assert "artifact_links" not in json_payload
    assert "links" not in json_payload["issue"]
    assert issue.id in compact
    assert compact_flag == compact
    assert opened == []


def test_show_malformed_graph_fails_loud_and_recovers_with_no_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        _install_show(monkeypatch, project, store)
        bad = plans / "links" / "202608" / "broken.md.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("{not-json", encoding="utf-8")

        _out, err, code = _show_err(issue.id, capsys)
        assert code == 1
        assert "Error:" in err
        assert "--no-links" in err
        recovered = _show(issue.id, capsys, "--no-links")
        assert issue.title in recovered
        assert "LINKS" not in recovered


def test_show_plain_rich_invariance_and_unicode_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        _install_show(monkeypatch, project, store)
        store.upsert_row(
            _row(
                f"bead:{issue.id}",
                "related",
                "plan:202608/日本語.md",
                description=(
                    "A very long reason about 日本語 wrapping that should break "
                    "across lines when the wrap budget is narrow enough."
                ),
            )
        )
        legacy = plans / "links" / "202608" / "legacy.md.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps(
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "artifact_ref": "plan:202608/legacy.md",
                    "rows": [
                        _row(
                            "plan:202608/legacy.md",
                            "related",
                            f"bead:{issue.id}",
                            origin="mystery-origin",
                            description="Legacy origin stays visible.",
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )

        plain = _show(
            issue.id,
            capsys,
            "--style",
            "plain",
            "--color",
            "always",
            "--wrap",
            "40",
        )
        rich = _show(
            issue.id,
            capsys,
            "--style",
            "rich",
            "--color",
            "always",
            "--wrap",
            "40",
        )

    assert strip_sgr(rich) == plain
    assert "mystery-origin" in plain
    assert "plan:202608/日本語.md" in plain
    assert "\x1b[" not in plain
    assert resolve_detail_style(style="plain", color="always") is DetailStyle.PLAIN
    reason_lines = [
        line
        for line in plain.splitlines()
        if line.startswith("    ") and "added " not in line and "mystery" not in line
    ]
    assert any(len(line) <= 40 for line in reason_lines)


def test_show_help_mentions_no_links_and_compact_never_expands() -> None:
    text = parser_for(("sase", "bead", "show")).format_help()
    assert "--no-links" in text
    assert "never expand" in text.lower()
