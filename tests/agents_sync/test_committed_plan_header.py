from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.commit_publication import refresh_committed_plan_header


def test_committed_plan_header_refresh_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from sase.sdd.associations import (
        PlanAgentAssociation,
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
    from sase.sdd.store import SddStore

    plans_root = tmp_path / "plans-sidecar"
    plan = plans_root / "202607" / "child.md"
    plan.parent.mkdir(parents=True)
    remote_sha = "f" * 40
    existing_header = render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.AGENTS,
                entries=(PlanHeaderEntry(label="remote.agent"),),
            ),
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.COMMITS,
                entries=(
                    PlanHeaderEntry(
                        label=remote_sha[:7],
                        target=f"https://example.test/commit/{remote_sha}",
                        trailing_text="fix: remote",
                    ),
                ),
            ),
        )
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/child.md](prompts/child.md)\n"
        f"{existing_header}\n\n"
        "# Child\n",
        encoding="utf-8",
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans_root,
        repo_root=plans_root,
    )
    local_sha = "a" * 40
    associations = PlanAssociations(
        agents=(
            PlanAgentAssociation(
                label="local.agent",
                target="https://example.test/agent",
                sort_key="local.agent",
            ),
        ),
        commits=(
            PlanCommitAssociation(
                label=local_sha[:7],
                target=f"https://example.test/commit/{local_sha}",
                trailing_text="feat: child",
                sort_key=(1, local_sha),
                sha=local_sha,
            ),
        ),
    )

    class _Index:
        def for_plan(self, plan_ref: str) -> PlanAssociations:
            assert plan_ref == "plan:202607/child.md"
            return associations

    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (tmp_path, 1),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.sdd.associations.build_plan_association_index",
        lambda *_args, **_kwargs: _Index(),
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        acquired_lock,
    )

    class _Resolver:
        def prompt_url(self, prompt_ref: str) -> str:
            assert prompt_ref == "prompts/202607/child.md"
            return "https://example.test/agents/prompts/202607/child.md"

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    commits: list[Path] = []

    def commit_plan(*_args: object, **kwargs: object) -> bool:
        paths = kwargs["paths"]
        assert isinstance(paths, list)
        commits.extend(Path(path) for path in paths)
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_plan)
    message = "feat: child\n\nSASE_PLAN=202607/child.md"

    first = refresh_committed_plan_header(message, primary_root=tmp_path)
    second = refresh_committed_plan_header(message, primary_root=tmp_path)

    assert first.changed and first.committed
    assert not second.changed and not second.committed
    assert commits == [plan]
    parsed = parse_plan_header_block(plan.read_text(encoding="utf-8"))
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.AGENTS,
        PlanHeaderSectionKind.COMMITS,
    ]
    assert parsed.sections[0].label == "prompts/202607/child.md"
    assert parsed.sections[0].target == (
        "https://example.test/agents/prompts/202607/child.md"
    )
    assert [entry.label for entry in parsed.sections[1].entries] == [
        "local.agent",
        "remote.agent",
    ]
    assert [entry.label for entry in parsed.sections[2].entries] == [
        local_sha[:7],
        remote_sha[:7],
    ]


def test_committed_plan_header_refresh_swallows_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(_root: Path) -> tuple[Path, int]:
        raise RuntimeError("plans unavailable")

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        fail,
    )

    outcome = refresh_committed_plan_header(
        "feat: child\n\nSASE_PLAN=202607/child.md",
        primary_root=tmp_path,
    )

    assert outcome.error == "plans unavailable"
    assert "Could not refresh committed plan header" in caplog.text
