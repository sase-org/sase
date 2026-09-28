"""Artifact-kind phase: ``goal:`` as a first-class builtin artifact kind.

Covers epic ``sase-1bu`` phase ``artifact-kind`` on the sase side: Python
builtin-entry dispatch, ``artifact read``/``show``/``path``, one-line
``@goal`` prompt expansion, staging, and ACE ``@goal:`` payload completion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.artifact_providers.builtin_entries import (
    BUILTIN_ENTRY_KIND_TYPES,
    resolve_builtin_entry,
)
from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefProject,
)
from sase.artifact_ref_prompt_context import PromptRefContext, PromptRefProject
from sase.artifact_refs import parse_artifact_ref
from sase.core import goal_ledger_facade as facade

_PROJECT_KEY = "acme_kind"


def _project(name: str = _PROJECT_KEY) -> ArtifactRefProject:
    return ArtifactRefProject(name=name, key=name, aliases=())


def _context(tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(_project(),),
        selected_project=_PROJECT_KEY,
    )


def _ref_context(context: ArtifactRefContext) -> PromptRefContext:
    return PromptRefContext(
        artifact_context=context,
        project=PromptRefProject(
            key=_PROJECT_KEY,
            display_name=_PROJECT_KEY,
            active_spec=Path("/tmp/x.sase"),
            archive_spec=Path("/tmp/x-archive.sase"),
        ),
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="explicit",
        vcs_ref=None,
    )


@pytest.fixture()
def goal_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """One local-mode goal; the ledger falls back to local with no primary."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    from sase.goals.store import resolve_goal_ledger

    ledger = resolve_goal_ledger(_PROJECT_KEY)
    assert ledger.mode == "local"
    facade.goal_ledger_init(ledger.root)
    outcome = facade.goal_ledger_append(
        ledger.root,
        {
            "action": {
                "action": "new",
                "title": "Kind goal",
                "outcome": "the kind resolves end to end",
                "criteria": [],
                "project": _PROJECT_KEY,
            },
            "actor": {"principal": "bryan.athena", "kind": "human"},
        },
    )
    assert outcome["status"] == "applied"
    return str(outcome["states"][0]["id"])


class TestGoalBuiltinDispatch:
    def test_goal_is_a_builtin_entry_kind(self) -> None:
        assert "goal" in BUILTIN_ENTRY_KIND_TYPES

    def test_resolve_exact_carries_goal_properties(
        self, tmp_path: Path, goal_id: str
    ) -> None:
        context = _context(tmp_path)
        outcome = resolve_builtin_entry(
            parse_artifact_ref(f"goal:{goal_id}"),
            context=context,
            ref_context=_ref_context(context),
        )
        assert outcome is not None
        assert outcome.status == "exact"
        assert outcome.entry is not None
        assert outcome.entry.properties["id"] == goal_id
        assert outcome.entry.properties["status"] == "active"
        assert outcome.entry.properties["title"] == "Kind goal"
        assert outcome.entry.properties["outcome"] == "the kind resolves end to end"
        assert outcome.resolved_path is not None
        assert str(outcome.resolved_path).endswith(f"items/{goal_id}")

    def test_unknown_goal_is_missing_with_help(
        self, tmp_path: Path, goal_id: str
    ) -> None:
        context = _context(tmp_path)
        outcome = resolve_builtin_entry(
            parse_artifact_ref("goal:aaaaa"),
            context=context,
            ref_context=_ref_context(context),
        )
        assert outcome is not None
        assert outcome.status == "missing"
        assert outcome.diagnostic is not None
        assert "aaaaa" in outcome.diagnostic
        assert "sase goal list" in outcome.diagnostic

    def test_unknown_project_reports_candidates(
        self, tmp_path: Path, goal_id: str
    ) -> None:
        context = _context(tmp_path)
        outcome = resolve_builtin_entry(
            parse_artifact_ref(f"goal:nope@{goal_id}"),
            context=context,
            ref_context=_ref_context(context),
        )
        assert outcome is not None
        assert outcome.status == "unknown_project"
        assert outcome.diagnostic is not None
        assert _PROJECT_KEY in outcome.diagnostic

    def test_settled_goal_still_cites(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_id: str
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        from sase.goals.store import resolve_goal_ledger

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        dropped = facade.goal_ledger_append(
            ledger.root,
            {
                "action": {
                    "action": "drop",
                    "goal_id": goal_id,
                    "why": "cited after settling",
                },
                "actor": {"principal": "bryan.athena", "kind": "human"},
            },
        )
        assert dropped["status"] == "applied"
        context = _context(tmp_path)
        outcome = resolve_builtin_entry(
            parse_artifact_ref(f"goal:{goal_id}"),
            context=context,
            ref_context=_ref_context(context),
        )
        assert outcome is not None
        assert outcome.status == "exact"
        assert outcome.entry is not None
        assert outcome.entry.properties["status"] == "dropped"


class TestGoalCardRender:
    def test_card_view_markdown_and_citation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_id: str
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        from sase.goals.store import resolve_goal_ledger

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        card = facade.goal_card_view(ledger.root, goal_id, "2026-09-28T15:00:00.000Z")
        assert card["goal_ref"] == f"goal:{goal_id}"
        markdown = facade.goal_card_markdown(card)
        assert "Kind goal" in markdown
        assert f"goal:{goal_id} · {_PROJECT_KEY} · ACTIVE" in markdown
        assert "the kind resolves end to end" in markdown
        line = facade.goal_citation_line(card)
        assert line.startswith(
            f'goal ⌖{goal_id} "Kind goal" in the {_PROJECT_KEY} project (active)'
        )
        assert len(line) <= 400

    def test_prompt_expansion_is_the_citation_line(
        self, tmp_path: Path, goal_id: str
    ) -> None:
        from sase.artifact_ref_prompt_rendering import _replacement_text
        from sase.artifact_refs import resolve_artifact_ref

        context = _context(tmp_path)
        ref_context = _ref_context(context)
        parsed = parse_artifact_ref(f"goal:{goal_id}")
        outcome = resolve_builtin_entry(
            parsed, context=context, ref_context=ref_context
        )
        assert outcome is not None
        resolution = resolve_artifact_ref(parsed, context=context)
        text = _replacement_text(
            parsed,
            resolution,
            context=context,
            resolved_path=outcome.resolved_path,
            issue_url_resolver=lambda project, number: "",
            entry=outcome.entry,
            display_path=None,
        )
        assert text.startswith(f'goal ⌖{goal_id} "Kind goal"')
        assert "@" not in text.split("goal ⌖")[0]


class TestGoalArtifactCli:
    def _other_goal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        from sase.goals.store import resolve_goal_ledger

        ledger = resolve_goal_ledger("other_kind")
        facade.goal_ledger_init(ledger.root)
        outcome = facade.goal_ledger_append(
            ledger.root,
            {
                "action": {
                    "action": "new",
                    "title": "Other goal",
                    "outcome": "cross-project citations resolve",
                    "criteria": [],
                    "project": "other_kind",
                },
                "actor": {"principal": "bryan.athena", "kind": "human"},
            },
        )
        assert outcome["status"] == "applied"
        return str(outcome["states"][0]["id"])

    def _resolve(self, tmp_path: Path, value: str):
        from sase.artifact_cli.references import resolve_cli_reference

        return resolve_cli_reference(
            value,
            context=ArtifactRefContext(
                document_roots=(),
                chats_root=tmp_path / "c",
                artifact_index_path=tmp_path / "i",
                repositories=(),
                projects=(_project(), _project("other_kind")),
                selected_project=_PROJECT_KEY,
            ),
        )

    def test_read_renders_the_markdown_card(self, tmp_path: Path, goal_id: str) -> None:
        from sase.artifact_cli.read import goal_card_body

        result = self._resolve(tmp_path, f"goal:{goal_id}")
        assert result.parsed.kind_type == "goal"
        assert result.resolution.status == "exact"
        body = goal_card_body(result)
        assert "Kind goal" in body
        assert "the kind resolves end to end" in body

    def test_show_carries_goal_metadata(self, tmp_path: Path, goal_id: str) -> None:
        result = self._resolve(tmp_path, f"goal:{goal_id}")
        assert result.entry is not None
        assert result.entry.ref_kind == "goal"
        assert result.entry.properties["title"] == "Kind goal"
        assert result.is_filesystem_backed

    def test_path_prints_the_goal_items_directory(
        self, tmp_path: Path, goal_id: str
    ) -> None:
        from sase.artifact_cli.references import resolved_file_path

        result = self._resolve(tmp_path, f"goal:{goal_id}")
        path = resolved_file_path(result)
        assert path is not None
        assert str(path).endswith(f"items/{goal_id}")

    def test_cross_project_citation_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_id: str
    ) -> None:
        other_id = self._other_goal(tmp_path, monkeypatch)
        result = self._resolve(tmp_path, f"goal:other_kind@{other_id}")
        assert result.resolution.status == "exact"
        assert result.entry is not None
        assert result.entry.project_display_name == "other_kind"
        assert result.entry.properties["title"] == "Other goal"


class TestGoalStagingAndCompletion:
    def test_goal_is_a_non_file_staged_kind(self) -> None:
        from sase.core.prompt_artifact_staging import _NON_FILE_REF_KINDS

        assert "goal" in _NON_FILE_REF_KINDS

    def test_completion_reads_unsettled_rows_from_the_projection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as catalogs

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        from sase.core.paths import sase_projects_dir

        projection = sase_projects_dir() / _PROJECT_KEY / "goals-hot.json"
        projection.parent.mkdir(parents=True)
        projection.write_text(
            json.dumps(
                {
                    "goals": {
                        "7k2mq": {
                            "row": {
                                "id": "7k2mq",
                                "status": "active",
                                "title": "Kind goal",
                                "updated_at": "2026-09-28T15:00:00.000Z",
                            }
                        },
                        "3fq9t": {
                            "row": {
                                "id": "3fq9t",
                                "status": "done",
                                "title": "Settled goal",
                                "updated_at": "2026-09-28T15:00:00.000Z",
                            }
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        context = _context(tmp_path)
        catalog = catalogs.load_goal_candidate_catalog(_PROJECT_KEY, context)
        assert [(row.payload, row.label) for row in catalog.rows] == [
            ("7k2mq", "Kind goal")
        ]
        assert catalog.truncated == 0

    def test_completion_catalog_carries_goal_payloads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as catalogs
        from sase.ace.tui.widgets._artifact_ref_completion_menu import (
            ArtifactRefCompletionCatalog,
            payload_rows,
        )

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        from sase.core.paths import sase_projects_dir

        projection = sase_projects_dir() / _PROJECT_KEY / "goals-hot.json"
        projection.parent.mkdir(parents=True)
        projection.write_text(
            json.dumps(
                {
                    "goals": {
                        "7k2mq": {
                            "row": {
                                "id": "7k2mq",
                                "status": "review",
                                "title": "Kind goal",
                                "updated_at": "2026-09-28T15:00:00.000Z",
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        context = _context(tmp_path)
        goals = catalogs.load_goal_candidate_catalog(_PROJECT_KEY, context)
        catalog = ArtifactRefCompletionCatalog(
            project=_PROJECT_KEY,
            kinds=("goal",),
            goals=goals.rows,
        )
        rows = dict(payload_rows("goal", catalog, commits=(), bugs=()))
        assert set(rows) == {"7k2mq"}
        assert rows["7k2mq"].source == "goal"
        assert rows["7k2mq"].label == "Kind goal"

    def test_goal_completion_badge_uses_the_goal_accent(self) -> None:
        from sase.ace.tui.widgets._prompt_input_bar_completion_rows_artifacts import (
            _ARTIFACT_SOURCE_BADGES,
        )

        assert _ARTIFACT_SOURCE_BADGES["goal"] == ("[⌖] ", "bold #FF87AF")

    def test_missing_projection_yields_no_goal_rows(self, tmp_path: Path) -> None:
        from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as catalogs

        catalog = catalogs.load_goal_candidate_catalog("no_such", _context(tmp_path))
        assert catalog.rows == ()
        assert catalog.truncated == 0
