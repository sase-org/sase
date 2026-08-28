"""Cross-project ``sase bead show`` CLI coverage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cross_project
from sase.bead.cross_project import AmbiguousBeadProjectError, BeadStoreOrigin
from sase.bead.model import BeadTier, Issue, IssueType
from sase.main.parser import create_parser


class _View:
    def __init__(self, issues: dict[str, Issue]) -> None:
        self.issues = issues
        self.seen: list[str] = []

    def __enter__(self) -> _View:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info

    def show(self, issue_id: str) -> Issue:
        self.seen.append(issue_id)
        if issue_id in self.issues:
            return self.issues[issue_id]
        matches = [
            issue
            for issue in self.issues.values()
            if issue.id.rsplit("-", maxsplit=1)[-1] == issue_id
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"ambiguous issue id: {issue_id}")
        raise KeyError(issue_id)

    def get_epic_children(self, issue_id: str) -> list[Issue]:
        canonical = self.show(issue_id).id
        return [issue for issue in self.issues.values() if issue.parent_id == canonical]

    def list_issues(self) -> list[Issue]:
        return list(self.issues.values())


@contextmanager
def _read_view(view: _View) -> Iterator[_View]:
    yield view


def _origin(tmp_path: Path, label: str = "bob-cli") -> BeadStoreOrigin:
    workspace = tmp_path / label
    return BeadStoreOrigin(
        project_key=f"gh_acme__{label}",
        project_label=label,
        primary_workspace=workspace,
        beads_dir=workspace / "sdd" / "beads",
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    local: _View,
    foreign: _View | None = None,
    origin: BeadStoreOrigin | None = None,
) -> None:
    monkeypatch.setattr("sase.bead.cli_query.get_read_view", lambda: _read_view(local))
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative", lambda *_a: False
    )
    monkeypatch.setattr("sase.bead.cli_query.plan_reference_roots", lambda *_a: ())
    monkeypatch.setattr(
        "sase.bead.cli_query.artifact_reference_context", lambda *_a: None
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda *_a: None,
    )
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda *_a: None)
    if origin is not None:
        monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)
        monkeypatch.setattr(
            cross_project,
            "origin_for_project_ref",
            lambda ref: (
                origin if ref in {origin.project_key, origin.project_label} else None
            ),
        )
    if foreign is not None:
        monkeypatch.setattr(
            "sase.bead.cli_show_router.open_bead_project_for_beads_dir",
            lambda _path: foreign,
        )


def _show(
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[str, str]:
    args = create_parser().parse_args(["bead", "show", *argv])
    bead_cli.handle_bead_show(args)
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_foreign_full_id_renders_foreign_bead_and_project_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    foreign_issue = Issue(
        id="bob-cli-1",
        title="Foreign",
        issue_type=IssueType.TASK,
    )
    origin = _origin(tmp_path)
    _install(
        monkeypatch,
        local=_View({}),
        foreign=_View({foreign_issue.id: foreign_issue}),
        origin=origin,
    )

    out, err = _show(capsys, "bob-cli-1", "--pager", "never")

    assert err == ""
    assert "bob-cli-1 · Foreign" in out
    assert "Project: bob-cli" in out


def test_local_success_does_not_consult_enabled_project_registry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(id="bob-cli-1", title="Local", issue_type=IssueType.TASK)
    local = _View({issue.id: issue})
    calls = 0

    def count_registry(*_args: object, **_kwargs: object) -> list[object]:
        nonlocal calls
        calls += 1
        return []

    _install(monkeypatch, local=local)
    monkeypatch.setattr(cross_project, "list_project_records", count_registry)

    out, err = _show(capsys, "bob-cli-1", "--format", "compact", "--pager", "never")

    assert err == ""
    assert "Local" in out
    assert calls == 0


def test_mixed_batch_uses_each_project_render_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_workspace = tmp_path / "local"
    foreign_workspace = tmp_path / "bob-cli"
    local_plan = local_workspace / "plans" / "202608" / "local.md"
    foreign_plan = foreign_workspace / "plans" / "202608" / "foreign.md"
    local_plan.parent.mkdir(parents=True)
    foreign_plan.parent.mkdir(parents=True)
    local_plan.write_text("# Local\n", encoding="utf-8")
    foreign_plan.write_text("# Foreign\n", encoding="utf-8")
    monkeypatch.chdir(local_workspace)

    local_issue = Issue(
        id="sase-1",
        title="Local Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202608/local.md",
    )
    foreign_issue = Issue(
        id="bob-cli-1",
        title="Foreign Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202608/foreign.md",
    )
    origin = BeadStoreOrigin(
        project_key="gh_acme__bob-cli",
        project_label="bob-cli",
        primary_workspace=foreign_workspace,
        beads_dir=foreign_workspace / "sdd" / "beads",
    )
    _install(
        monkeypatch,
        local=_View({local_issue.id: local_issue}),
        foreign=_View({foreign_issue.id: foreign_issue}),
        origin=origin,
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative", lambda *_a: True
    )

    def plan_roots(workspace: Path | None = None) -> tuple[Path, ...]:
        root = local_workspace if workspace is None else workspace
        return (root / "plans",)

    def page_url(bead_id: str, workspace: Path | None = None) -> str:
        label = "local" if workspace is None else workspace.name
        return f"https://example.test/{label}/{bead_id}"

    monkeypatch.setattr("sase.bead.cli_query.plan_reference_roots", plan_roots)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", page_url)

    out, err = _show(
        capsys,
        "sase-1",
        "bob-cli-1",
        "--pager",
        "never",
    )

    assert err == ""
    assert "plans:202608/local.md\n  → plans/202608/local.md" in out
    assert "plans:202608/foreign.md\n  → plans/202608/foreign.md" in out
    assert "https://example.test/local/sase-1" in out
    assert "https://example.test/bob-cli/bob-cli-1" in out


def test_unknown_prefix_preserves_issue_not_found_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch, local=_View({}))
    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: None)
    args = create_parser().parse_args(
        ["bead", "show", "bob-cli-1", "--format", "compact", "--pager", "never"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: issue not found: bob-cli-1\n"


def test_known_project_without_materialized_store_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin = BeadStoreOrigin(
        project_key="gh_acme__bob-cli",
        project_label="bob-cli",
        primary_workspace=tmp_path / "bob-cli",
        beads_dir=None,
    )
    _install(monkeypatch, local=_View({}))
    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)
    args = create_parser().parse_args(
        ["bead", "show", "bob-cli-1", "--format", "compact", "--pager", "never"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert "project 'bob-cli' owns 'bob-cli-1'" in captured.err
    assert "not materialized" in captured.err


def test_ambiguous_prefix_names_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _origin(tmp_path, "bob-cli")
    second = BeadStoreOrigin(
        project_key="other",
        project_label="bob-cli",
        primary_workspace=tmp_path / "other",
        beads_dir=tmp_path / "other" / "sdd" / "beads",
    )

    def ambiguous(_id: str) -> object:
        raise AmbiguousBeadProjectError(
            "bob-cli",
            [first, second],
            subject="bead prefix",
        )

    _install(monkeypatch, local=_View({}))
    monkeypatch.setattr(cross_project, "origin_for_bead_id", ambiguous)
    args = create_parser().parse_args(
        ["bead", "show", "bob-cli-1", "--format", "compact", "--pager", "never"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "ambiguous bead prefix 'bob-cli'" in captured.err
    assert "gh_acme__bob-cli" in captured.err
    assert "other" in captured.err
    assert "-P/--project" in captured.err


def test_foreign_epic_expansion_uses_foreign_store_for_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_child = Issue(
        id="bob-cli-e.1",
        title="Local Collision",
        issue_type=IssueType.PHASE,
        parent_id="bob-cli-e",
    )
    foreign_epic = Issue(
        id="bob-cli-e",
        title="Foreign Epic",
        issue_type=IssueType.PLAN,
    )
    foreign_child = Issue(
        id="bob-cli-e.1",
        title="Foreign Child",
        issue_type=IssueType.PHASE,
        parent_id=foreign_epic.id,
    )
    origin = _origin(tmp_path)
    _install(
        monkeypatch,
        local=_View({local_child.id: local_child}),
        foreign=_View({foreign_epic.id: foreign_epic, foreign_child.id: foreign_child}),
        origin=origin,
    )

    out, err = _show(
        capsys,
        "bob-cli-e..",
        "--format",
        "compact",
        "--pager",
        "never",
    )

    assert err == ""
    assert "Foreign Epic" in out
    assert "Foreign Child" in out
    assert "Local Collision" not in out


def test_project_option_pins_store_and_allows_shorthand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    foreign_issue = Issue(id="bob-cli-1", title="Pinned", issue_type=IssueType.TASK)
    origin = _origin(tmp_path)
    _install(
        monkeypatch,
        local=_View({}),
        foreign=_View({foreign_issue.id: foreign_issue}),
        origin=origin,
    )

    out, err = _show(
        capsys,
        "1",
        "--project",
        "bob-cli",
        "--format",
        "compact",
        "--pager",
        "never",
    )

    assert err == ""
    assert "bob-cli-1" in out
    assert "Pinned" in out


def test_project_option_rejects_unknown_ref(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch, local=_View({}))
    monkeypatch.setattr(cross_project, "origin_for_project_ref", lambda _ref: None)
    args = create_parser().parse_args(["bead", "show", "1", "--project", "missing"])

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: project 'missing' was not found\n"


def test_foreign_json_keeps_existing_envelope_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    foreign_issue = Issue(
        id="bob-cli-1",
        title="Foreign",
        issue_type=IssueType.TASK,
    )
    origin = _origin(tmp_path)
    _install(
        monkeypatch,
        local=_View({}),
        foreign=_View({foreign_issue.id: foreign_issue}),
        origin=origin,
    )

    out, err = _show(
        capsys,
        "bob-cli-1",
        "--format",
        "json",
        "--pager",
        "never",
    )

    payload = json.loads(out)
    assert err == ""
    assert payload["issue"]["id"] == "bob-cli-1"
    assert "project" not in payload
