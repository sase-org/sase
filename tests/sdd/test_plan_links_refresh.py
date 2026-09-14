"""Tests for tree-wide plan provenance reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

import pytest

from sase.sdd.associations import (
    PlanAgentAssociation,
    PlanAssociationIndex,
    PlanAssociations,
    PlanCommitAssociation,
)
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    render_plan_header_block,
)
from sase.sdd.plan_links_refresh import refresh_plan_links
from sase.sdd.store import SddStore


def _store(root: Path) -> SddStore:
    root.mkdir()
    return SddStore("sidecar_repos", root, root)


def _write_plan(
    root: Path,
    name: str,
    *,
    tier: str = "tale",
    parent: str | None = None,
    bead: str | None = None,
) -> Path:
    path = root / "202607" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_line = f"parent: {parent}\n" if parent else ""
    bead_line = f"bead: {bead}\n" if bead else ""
    path.write_text(
        f"---\ntier: {tier}\ntitle: {name}\ngoal: Test\n"
        f"{parent_line}{bead_line}---\n# {name}\n",
        encoding="utf-8",
    )
    return path


def _commit(sha: str, subject: str, order: int = 1) -> PlanCommitAssociation:
    return PlanCommitAssociation(
        label=sha[:7],
        target=f"https://example.test/commit/{sha}",
        trailing_text=subject,
        sort_key=(order, sha),
        sha=sha,
    )


@contextmanager
def _acquired_lock(*_args: object, **_kwargs: object):
    yield True


def test_refresh_dry_run_write_and_second_write_are_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    _write_plan(root, "epic", tier="epic")
    child = _write_plan(
        root,
        "child",
        parent="plans:202607/epic.md",
    )
    associations = PlanAssociations(
        agents=(PlanAgentAssociation("owner.host.agent", None, "owner.host.agent"),),
        commits=(
            PlanCommitAssociation(
                "abcdef0",
                None,
                "feat: child",
                (1, "abcdef012345"),
                "abcdef012345",
            ),
        ),
    )
    index = PlanAssociationIndex(
        MappingProxyType({"plan:202607/child.md": associations})
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    committed: list[tuple[Path, ...]] = []

    def commit(*_args: object, **kwargs: object) -> bool:
        committed.append(tuple(Path(path) for path in kwargs["paths"]))
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    before = child.read_text(encoding="utf-8")

    dry = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
    )

    assert dry.ok
    assert dry.scanned == 2
    assert [action.path for action in dry.actions] == ["202607/child.md"]
    assert dry.actions[0].parent_migrated
    assert dry.changed_files == ()
    assert child.read_text(encoding="utf-8") == before

    written = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
        write=True,
    )

    assert written.ok and written.committed
    assert written.changed_files == ("202607/child.md",)
    assert committed == [(child,)]
    content = child.read_text(encoding="utf-8")
    assert "\nparent:" not in content
    assert "— feat: child" in content
    assert "— —" not in content
    parsed = parse_plan_header_block(content)
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.PARENT,
        PlanHeaderSectionKind.AGENTS,
        PlanHeaderSectionKind.COMMITS,
    ]

    second = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
        write=True,
    )

    assert second.ok
    assert second.actions == ()
    assert second.changed_files == ()
    assert not second.committed
    assert committed == [(child,)]


def test_refresh_reports_unresolved_legacy_parent_without_dropping_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    child = _write_plan(root, "child", parent="plans:202607/missing.md")
    before = child.read_text(encoding="utf-8")
    index = PlanAssociationIndex(MappingProxyType({}))

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
    )

    assert not report.ok
    assert report.errors[0].code == "parent-unresolved"
    assert report.actions == ()
    assert child.read_text(encoding="utf-8") == before


def test_refresh_plan_scope_rejects_missing_reference(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    _write_plan(root, "child")

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        plan_ref="plans:202607/missing.md",
        association_index=PlanAssociationIndex(MappingProxyType({})),
    )

    assert not report.ok
    assert report.scanned == 0
    assert report.errors[0].code == "plan-unresolved"


def test_refresh_backfills_bead_section_from_frontmatter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    plan = _write_plan(root, "child", bead="sase-ai.8")
    index = PlanAssociationIndex(MappingProxyType({}))

    class _Resolver:
        def bead_url(self, bead_id: str) -> str:
            assert bead_id == "sase-ai.8"
            return "https://example.test/pages/sase-ai/sase-ai.8.md"

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
        write=True,
    )

    assert report.ok
    assert [action.path for action in report.actions] == ["202607/child.md"]
    bead = parse_plan_header_block(plan.read_text(encoding="utf-8")).sections[0]
    assert bead.kind is PlanHeaderSectionKind.BEAD
    assert bead.label == "sase-ai.8"
    assert bead.target == "https://example.test/pages/sase-ai/sase-ai.8.md"


def test_refresh_retargets_existing_prompt_section_to_agents_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    plan = _write_plan(root, "child")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "# child\n",
            "- **PROMPT:** [202607/prompts/child.md](prompts/child.md)\n\n# child\n",
        ),
        encoding="utf-8",
    )

    class Resolver:
        def prompt_url(self, prompt_ref: str) -> str:
            assert prompt_ref == "prompts/202607/child.md"
            return "https://example.test/agents/prompts/202607/child.md"

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: Resolver(),
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=PlanAssociationIndex(MappingProxyType({})),
        write=True,
    )

    assert report.ok and report.committed
    prompt = parse_plan_header_block(plan.read_text(encoding="utf-8")).sections[0]
    assert prompt.kind is PlanHeaderSectionKind.PROMPT
    assert prompt.label == "prompts/202607/child.md"
    assert prompt.target == "https://example.test/agents/prompts/202607/child.md"


def test_refresh_plan_links_empty_local_view_does_not_drop_existing_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    plan = _write_plan(root, "child")
    header = render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.AGENTS,
                entries=(PlanHeaderEntry(label="remote.agent"),),
            ),
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.COMMITS,
                entries=(
                    PlanHeaderEntry(
                        label="bbbbbbb",
                        target="https://example.test/commit/" + "b" * 40,
                        trailing_text="outside view",
                    ),
                ),
            ),
        )
    )
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("# child\n", f"{header}\n# child\n"),
        encoding="utf-8",
    )
    before = plan.read_text(encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=PlanAssociationIndex(MappingProxyType({})),
        write=True,
    )

    assert report.ok
    assert report.actions == ()
    assert report.changed_files == ()
    assert plan.read_text(encoding="utf-8") == before


def test_refresh_plan_links_two_writer_provenance_order_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    plan = _write_plan(root, "child")
    original = plan.read_text(encoding="utf-8")
    first_sha = "1" * 40
    second_sha = "2" * 40
    first = PlanAssociationIndex(
        MappingProxyType(
            {
                "plan:202607/child.md": PlanAssociations(
                    agents=(PlanAgentAssociation("first.agent", None, "first.agent"),),
                    commits=(_commit(first_sha, "feat: first", order=1),),
                )
            }
        )
    )
    second = PlanAssociationIndex(
        MappingProxyType(
            {
                "plan:202607/child.md": PlanAssociations(
                    agents=(
                        PlanAgentAssociation("second.agent", None, "second.agent"),
                    ),
                    commits=(_commit(second_sha, "feat: second", order=2),),
                )
            }
        )
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    first_report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=first,
        write=True,
    )
    second_report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=second,
        write=True,
    )
    first_then_second = plan.read_text(encoding="utf-8")
    plan.write_text(original, encoding="utf-8")
    reverse_first_report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=second,
        write=True,
    )
    reverse_second_report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=first,
        write=True,
    )
    second_then_first = plan.read_text(encoding="utf-8")

    assert first_report.ok
    assert second_report.ok
    assert reverse_first_report.ok
    assert reverse_second_report.ok
    assert first_then_second == second_then_first
    parsed = parse_plan_header_block(first_then_second)
    agents = next(
        section
        for section in parsed.sections
        if section.kind is PlanHeaderSectionKind.AGENTS
    )
    commits = next(
        section
        for section in parsed.sections
        if section.kind is PlanHeaderSectionKind.COMMITS
    )
    assert [entry.label for entry in agents.entries] == [
        "first.agent",
        "second.agent",
    ]
    assert [entry.label for entry in commits.entries] == [
        first_sha[:7],
        second_sha[:7],
    ]
