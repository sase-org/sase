"""Catalog isolation, native-index memoization, and cap accounting."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sase_core_rs import artifact_ref_payload_inventory

from tests._scratch_resource_probe import scratch_resource_report

from sase.artifact_ref_prompt import _resolve_for_launch
from sase.ace.tui.widgets import artifact_ref_completion as artifact_completion
from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefCommitCandidate,
    ArtifactRefCompletionCatalog,
    ArtifactRefPayloadCompletionMetadata,
    _ArtifactRefDocumentCandidate,
    build_artifact_ref_completion_result,
    detect_artifact_ref_completion_context,
    load_artifact_ref_completion_catalog,
)
from sase.ace.tui.widgets.prompt_commit_inventory import (
    load_prompt_commit_snapshot,
)
from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefRepository,
    parse_artifact_ref,
)


_KINDS = ("commit", "plans", "research")
_CATALOG = ArtifactRefCompletionCatalog(
    project=None,
    kinds=_KINDS,
    documents=(
        _ArtifactRefDocumentCandidate("plans", "alpha.md", "Alpha"),
        _ArtifactRefDocumentCandidate("plans", "beta.md", "Beta"),
    ),
)


def test_document_catalog_loads_each_role_without_prompt_corpus_starvation(
    tmp_path,
) -> None:
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    context = ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot("plans", plans),
            ArtifactRefDocumentRoot("research", research),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "missing-index.jsonl",
        repositories=(),
        projects=(),
    )

    def match(relpath: str, title: str) -> SimpleNamespace:
        return SimpleNamespace(
            plan=SimpleNamespace(
                relpath=relpath,
                title=title,
                created_at="2026-07-30T00:00:00Z",
            )
        )

    def search(**kwargs):
        corpora = kwargs["document_corpora"]
        assert "prompt" not in kwargs["kinds"]
        assert {"plans", "research", "tale", "epic"} <= set(kwargs["kinds"])
        assert len(corpora) == 1
        role = corpora[0][1]
        if role == "plans":
            return [
                match("202607/one.md", "One"),
                match("202607/two.md", "Two"),
                match("202607/three.md", "Three"),
            ]
        assert role == "research"
        return [
            match(
                "202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md",
                "SASE Sites Hub and Pages",
            )
        ]

    with (
        patch("sase.plan_search.facade.search", side_effect=search) as search_mock,
        patch("sase.history.chat_storage.iter_chat_files", return_value=()),
        patch(
            "sase.ace.tui.widgets.artifact_ref_completion._MAX_DOCUMENT_ROWS_PER_KIND",
            2,
        ),
    ):
        catalog = load_artifact_ref_completion_catalog(None, context)

    assert search_mock.call_count == 2
    assert [(row.kind, row.payload) for row in catalog.documents] == [
        ("plans", "202607/one.md"),
        ("plans", "202607/two.md"),
        (
            "research",
            "202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md",
        ),
    ]
    assert catalog.payload_truncation["plans"] == 1
    assert catalog.payload_truncation["research"] == 0

    completion_context = detect_artifact_ref_completion_context(
        "@research:site",
        len("@research:site"),
        context.known_kinds,
    )
    assert completion_context is not None
    result = build_artifact_ref_completion_result(completion_context, catalog)
    assert [candidate.insertion for candidate in result.candidates] == [
        "@research:202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md"
    ]
    metadata = result.candidates[0].metadata
    assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
    assert metadata.label_match == ((37, 41),)
    assert metadata.title_match == ((5, 9),)
    assert metadata.match_tier == 2
    assert result.truncated_payloads == 0


def test_warm_payload_index_and_metadata_are_reused_across_keystrokes() -> None:
    first_context = detect_artifact_ref_completion_context(
        "@plans:alpha",
        len("@plans:alpha"),
        _KINDS,
    )
    second_context = detect_artifact_ref_completion_context(
        "@plans:beta",
        len("@plans:beta"),
        _KINDS,
    )
    assert first_context is not None
    assert second_context is not None
    expected_index = _CATALOG.payload_indexes["plans"]
    expected_metadata = _CATALOG.payload_metadata["plans"]

    with patch(
        "sase.ace.tui.widgets.artifact_ref_completion.at_reference_menu",
        wraps=artifact_completion.at_reference_menu,
    ) as menu:
        build_artifact_ref_completion_result(first_context, _CATALOG)
        build_artifact_ref_completion_result(second_context, _CATALOG)

    assert len(menu.call_args_list) == 2
    assert all(
        call.kwargs["payload_index"] is expected_index for call in menu.call_args_list
    )
    assert _CATALOG.payload_metadata["plans"] is expected_metadata


def test_payload_counts_and_truncation_are_propagated_from_catalog() -> None:
    catalog = ArtifactRefCompletionCatalog(
        project=None,
        kinds=("plans",),
        documents=(
            _ArtifactRefDocumentCandidate("plans", "one.md", "One"),
            _ArtifactRefDocumentCandidate("plans", "two.md", "Two"),
        ),
        truncated_payloads_by_kind=(("plans", 17),),
    )
    context = detect_artifact_ref_completion_context(
        "@plans:",
        len("@plans:"),
        catalog.kinds,
    )
    assert context is not None

    result = build_artifact_ref_completion_result(context, catalog)

    assert result.payload_count == 2
    assert result.payload_total == 19
    assert result.truncated_payloads == 17


def test_dynamic_payload_index_is_memoized_by_snapshot_identity() -> None:
    commits = (
        ArtifactRefCommitCandidate(
            "sase@" + "a" * 12,
            "Alpha commit",
            scope="sase",
            rank=0,
            body="Alpha body",
        ),
        ArtifactRefCommitCandidate(
            "sase@" + "b" * 12,
            "Beta commit",
            scope="sase",
            rank=1,
        ),
    )
    first_context = detect_artifact_ref_completion_context(
        "@commit:alpha",
        len("@commit:alpha"),
        _KINDS,
    )
    second_context = detect_artifact_ref_completion_context(
        "@commit:beta",
        len("@commit:beta"),
        _KINDS,
    )
    assert first_context is not None
    assert second_context is not None
    artifact_completion._SNAPSHOT_PAYLOAD_MEMOS.pop("commit", None)

    with patch(
        "sase.ace.tui.widgets.artifact_ref_completion.at_reference_inventory",
        wraps=artifact_completion.at_reference_inventory,
    ) as inventory:
        build_artifact_ref_completion_result(
            first_context,
            _CATALOG,
            commits=commits,
        )
        build_artifact_ref_completion_result(
            second_context,
            _CATALOG,
            commits=commits,
        )

    inventory.assert_called_once()
    assert inventory.call_args.args[0][0] == {
        "payload": "sase@" + "a" * 12,
        "label": "Alpha commit",
        "detail": "",
        "age": "",
        "scope": "sase",
        "rank": 0,
        "body": "Alpha body",
    }


def test_commit_completion_rows_match_shared_inventory_and_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Set the budget explicitly rather than relying on sase-core's default
    # (currently 30s) being generous enough on a heavily oversubscribed CI
    # runner; see SASE_ARTIFACT_REF_COMMIT_TIMEOUT in sase-core's
    # editor/completion.rs.
    monkeypatch.setenv("SASE_ARTIFACT_REF_COMMIT_TIMEOUT", "30")
    first = tmp_path / "sase"
    second = tmp_path / "sase-core"
    sidecar = tmp_path / "plans"
    _init_git_repo(first)
    _init_git_repo(second)
    _init_git_repo(sidecar)
    recent_sha = _commit_at(second, 1_700_000_100, "fix(core): ranked row")
    older_sha = _commit_at(first, 1_700_000_000, "docs: older row")
    sidecar_sha = _commit_at(sidecar, 1_700_000_200, "chore(plans): sync from agent")
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(
            ArtifactRefRepository(
                "sase",
                checkout_path=first,
                checkout_paths=(first,),
                kind="primary",
            ),
            ArtifactRefRepository(
                "sase-core",
                checkout_path=second,
                checkout_paths=(second,),
                kind="linked",
            ),
            ArtifactRefRepository(
                "plans",
                checkout_path=sidecar,
                checkout_paths=(sidecar,),
                kind="sidecar",
            ),
        ),
        projects=(),
    )
    raw_inventory = artifact_ref_payload_inventory("commit", context.to_wire())
    lsp_payload_sequence = tuple(
        f"@commit:{row['payload']}"
        for row in raw_inventory["payloads"]
        if isinstance(row, dict)
    )

    catalog = ArtifactRefCompletionCatalog(project=None, kinds=("commit",))
    snapshot = load_prompt_commit_snapshot(None, context, loaded_at=1.0)
    completion_context = detect_artifact_ref_completion_context(
        "@commit:",
        len("@commit:"),
        catalog.kinds,
    )
    assert completion_context is not None

    result = build_artifact_ref_completion_result(
        completion_context,
        catalog,
        commits=snapshot.rows,
        commits_truncated_payloads=snapshot.truncated_payloads,
    )
    prompt_payload_sequence = tuple(
        candidate.insertion for candidate in result.candidates
    )

    # An empty inventory means sase-core gave up on `git log` -- on CI runners
    # that has been CommitLogFailure::Scratch, whose message discards the
    # errno.  Report the scratch-file resource state next to it rather than
    # weakening the parity assertion below.
    probe = ""
    if not lsp_payload_sequence or not prompt_payload_sequence:
        probe = "\n" + scratch_resource_report()
        print(probe, file=sys.stderr)

    assert lsp_payload_sequence == prompt_payload_sequence, probe
    assert prompt_payload_sequence == (
        f"@commit:sase-core@{recent_sha[:12]}",
        f"@commit:sase@{older_sha[:12]}",
    ), probe
    assert sidecar_sha[:12] not in " ".join(lsp_payload_sequence)
    assert raw_inventory["truncated_payloads"] == 0
    assert snapshot.truncated_payloads == 0
    for insertion in prompt_payload_sequence:
        parsed = parse_artifact_ref(insertion.removeprefix("@"))
        resolution = _resolve_for_launch(parsed, context=context)
        assert resolution.status != "missing"
        assert resolution.locator is not None

    sidecar_reference = parse_artifact_ref(f"commit:plans@{sidecar_sha[:12]}")
    sidecar_resolution = _resolve_for_launch(sidecar_reference, context=context)
    assert sidecar_resolution.status != "missing"
    assert sidecar_resolution.locator is not None


def _init_git_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "commit-completion@example.com")
    _git(repo, "config", "user.name", "Commit Completion")
    _git(repo, "remote", "add", "origin", str(repo))


def _commit_at(repo: Path, timestamp: int, message: str) -> str:
    filename = f"{timestamp}.txt"
    (repo / filename).write_text(f"{message}\n", encoding="utf-8")
    _git(repo, "add", filename)
    env = {
        "GIT_AUTHOR_DATE": f"{timestamp} +0000",
        "GIT_COMMITTER_DATE": f"{timestamp} +0000",
    }
    _git(repo, "commit", "-q", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD").strip()


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=None if env is None else {**os.environ, **env},
    )
    return result.stdout
