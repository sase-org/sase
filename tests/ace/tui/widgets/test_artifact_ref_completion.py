"""Pure and widget coverage for kind-tagged artifact completion."""

from __future__ import annotations

from dataclasses import replace
import os
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets._file_completion_base import (
    _PromptPathInventoryWorkerResult,
)
from sase.ace.tui.widgets._artifact_ref_entity_catalogs import (
    ArtifactRefAgentCandidate,
    ArtifactRefBeadCandidate,
    _BEAD_CACHE,
    load_agent_candidates,
    load_bead_candidates,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefBugCandidate,
    _ArtifactRefChatCandidate,
    ArtifactRefCommitCandidate,
    ArtifactRefCompletionCatalog,
    _ARTIFACT_INDEX_CACHE,
    _ArtifactRefDocumentCandidate,
    _ArtifactRefFileCandidate,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    _load_artifact_file_candidates,
    _read_cached_artifact_index,
    build_artifact_ref_completion_result,
    detect_artifact_ref_completion_context,
    load_artifact_ref_completion_catalog,
)
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefProject,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_path_inventory import (
    PromptPathRow,
    PromptPathSnapshot,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.artifact_file_types import ArtifactFile
from sase.bead.model import BeadTier, Issue, IssueType, Status

from ._completion_helpers import CompletionTestApp


_KINDS = (
    "commit",
    "chat",
    "bug",
    "file",
    "bead",
    "agent",
    "plans",
    "designs",
)
_CATALOG = ArtifactRefCompletionCatalog(
    project=None,
    kinds=_KINDS,
    documents=(
        _ArtifactRefDocumentCandidate(
            "plans",
            "202607/alpha.md",
            "Alpha plan",
            "2026-07-29T12:00:00Z",
        ),
        _ArtifactRefDocumentCandidate(
            "plans",
            "202607/beta.md",
            "Beta plan",
            "2026-07-28T12:00:00Z",
        ),
        _ArtifactRefDocumentCandidate(
            "designs",
            "202607/layout.md",
            "Layout",
            "2026-07-27T12:00:00Z",
        ),
    ),
    artifact_files=(
        _ArtifactRefFileCandidate(
            "explicit:abc123",
            "Architecture diagram",
            "image",
            "2026-07-29T12:00:00Z",
        ),
    ),
    chats=(_ArtifactRefChatCandidate("202607/agent.md", 1_785_326_400),),
    beads=(
        ArtifactRefBeadCandidate(
            "sase-9z",
            "Artifact references",
            "in_progress · epic",
            "2026-07-29T12:00:00Z",
        ),
    ),
    agents=(
        ArtifactRefAgentCandidate(
            "bbugyi200.athena.9w",
            "9w",
            "sase",
            1_785_326_400,
        ),
    ),
)


def _seed_catalog(
    text_area: PromptTextArea,
    catalog: ArtifactRefCompletionCatalog,
    *,
    project: str | None = None,
) -> None:
    text_area._artifact_ref_known_kinds_by_project[project] = frozenset(catalog.kinds)
    text_area._artifact_ref_completion_catalogs_by_project[project] = catalog


def _seed_paths(
    text_area: PromptTextArea,
    directory: str,
    rows: tuple[PromptPathRow, ...],
) -> str:
    key = text_area._prompt_path_directory_key(directory)
    text_area._prompt_path_snapshots[key] = PromptPathSnapshot(key, rows, (1, 1))
    # Keep the synthetic snapshot stable instead of letting a real worker
    # revalidate the test process's directory.
    text_area._prompt_path_inflight.add(key)
    return key


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    (
        ("@", 1, ("kind", "", "", 0, 1)),
        ("@pl", 3, ("kind", "pl", "", 0, 3)),
        ("x @plans:", 9, ("payload", "plans", "", 2, 9)),
        (
            "x @plans:202607/old.md done",
            13,
            ("payload", "plans", "2026", 2, 22),
        ),
    ),
)
def test_detect_artifact_ref_context_at_kind_and_payload_positions(
    text: str,
    cursor: int,
    expected: tuple[str, str, str, int, int],
) -> None:
    context = detect_artifact_ref_completion_context(text, cursor, _KINDS)

    assert context is not None
    assert (
        context.stage,
        context.partial_kind,
        context.partial_payload,
        context.replacement_start,
        context.replacement_end,
    ) == expected


@pytest.mark.parametrize(
    "text", ("@~/notes.md", "@/tmp/notes.md", "@./notes.md", "@../notes.md")
)
def test_detector_keeps_path_shaped_tokens_in_kind_stage(text: str) -> None:
    context = detect_artifact_ref_completion_context(text, len(text), _KINDS)

    assert context is not None
    assert context.stage == "kind"
    assert context.path_directory is not None


def test_detector_converts_rust_byte_spans_to_python_offsets() -> None:
    text = "😀 @pl"

    context = detect_artifact_ref_completion_context(text, len(text), _KINDS)

    assert context is not None
    assert (context.replacement_start, context.replacement_end) == (2, 5)
    assert (context.query_start, context.query_end) == (3, 5)


@pytest.mark.parametrize(
    "text",
    ("person@example:thing", "(@plans:thing.md)", "`@plans:thing.md`", "@foo!"),
)
def test_detector_declines_invalid_left_context_literals_and_punctuation(
    text: str,
) -> None:
    assert detect_artifact_ref_completion_context(text, len(text), _KINDS) is None


def test_kind_rows_filter_case_insensitively_and_keep_dynamic_metadata() -> None:
    context = detect_artifact_ref_completion_context("@PL", 3, _KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(context, _CATALOG)

    assert [candidate.insertion for candidate in result.candidates] == ["@plans:"]
    metadata = result.candidates[0].metadata
    assert isinstance(metadata, ArtifactRefKindCompletionMetadata)
    assert (metadata.kind, metadata.builtin) == ("plans", False)


def test_payload_rows_keep_full_prefix_metadata_and_shared_extension() -> None:
    context = detect_artifact_ref_completion_context(
        "@plans:202607/",
        len("@plans:202607/"),
        _KINDS,
    )
    assert context is not None

    result = build_artifact_ref_completion_result(context, _CATALOG)

    assert [candidate.insertion for candidate in result.candidates] == [
        "@plans:202607/beta.md",
        "@plans:202607/alpha.md",
    ]
    assert result.shared_extension == ""
    metadata = result.candidates[0].metadata
    assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
    assert (metadata.source, metadata.label) == ("document", "Beta plan")


@pytest.mark.parametrize(
    ("token", "display", "insertion", "source", "label", "detail"),
    (
        (
            "@bead:",
            "sase-9z",
            "@bead:sase-9z",
            "bead",
            "Artifact references",
            "in_progress · epic",
        ),
        (
            "@agent:",
            "bbugyi200.athena.9w",
            "@agent:bbugyi200.athena.9w",
            "agent",
            "9w",
            "sase",
        ),
    ),
)
def test_entity_rows_keep_readable_labels_and_durable_payloads(
    token: str,
    display: str,
    insertion: str,
    source: str,
    label: str,
    detail: str,
) -> None:
    context = detect_artifact_ref_completion_context(token, len(token), _KINDS)
    assert context is not None

    candidate = build_artifact_ref_completion_result(context, _CATALOG).candidates[0]

    assert (candidate.display, candidate.insertion) == (display, insertion)
    metadata = candidate.metadata
    assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
    assert (metadata.source, metadata.label, metadata.detail) == (
        source,
        label,
        detail,
    )


def test_kind_menu_filters_artifacts_and_files_through_shared_policy() -> None:
    context = detect_artifact_ref_completion_context("@pl", 3, _KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(
        context,
        _CATALOG,
        paths=(PromptPathRow("plans", True), PromptPathRow("plain.txt", False)),
    )

    assert [candidate.insertion for candidate in result.candidates] == [
        "@plans:",
        "@plans/",
        "@plain.txt",
    ]
    assert isinstance(result.candidates[0].metadata, ArtifactRefKindCompletionMetadata)
    assert all(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in result.candidates[1:]
    )


def test_path_query_returns_only_rows_from_the_requested_directory() -> None:
    context = detect_artifact_ref_completion_context("@src/", 5, _KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(
        context,
        _CATALOG,
        paths=(PromptPathRow("pkg", True), PromptPathRow("main.py", False)),
    )

    assert [candidate.insertion for candidate in result.candidates] == [
        "@src/pkg/",
        "@src/main.py",
    ]
    assert all(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in result.candidates
    )


async def test_bare_at_opens_artifacts_then_files() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        _seed_paths(
            text_area,
            "",
            (PromptPathRow("src", True), PromptPathRow("Justfile", False)),
        )

        await pilot.press("@")

        assert text_area._completion_kind == ARTIFACT_REF_COMPLETION_KIND
        assert text_area._file_completion_active is True
        insertions = [row.insertion for row in text_area._file_completion_candidates]
        first_file = next(
            index
            for index, row in enumerate(text_area._file_completion_candidates)
            if isinstance(row.metadata, AtReferenceFileCompletionMetadata)
        )
        assert all(
            not isinstance(row.metadata, AtReferenceFileCompletionMetadata)
            for row in text_area._file_completion_candidates[:first_file]
        )
        assert insertions[first_file:] == ["@src/", "@Justfile"]


async def test_directory_accept_drills_down_and_file_accept_closes() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        _seed_paths(text_area, "", (PromptPathRow("src", True),))
        _seed_paths(text_area, "src/", (PromptPathRow("main.py", False),))
        text_area.load_text("@sr")
        text_area.cursor_location = (0, 3)

        assert text_area._try_artifact_ref_completion() is True
        await pilot.press("enter")

        assert text_area.text == "@src/"
        assert text_area._file_completion_active is True
        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@src/main.py"
        ]

        await pilot.press("enter")
        assert text_area.text == "@src/main.py"
        assert text_area._file_completion_active is False


async def test_bare_at_enter_submits_but_ctrl_l_and_navigation_accept() -> None:
    app = CompletionTestApp()
    submitted = 0
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        _seed_paths(text_area, "", ())

        def record_submit() -> None:
            nonlocal submitted
            submitted += 1

        text_area.action_submit_prompt = record_submit  # type: ignore[method-assign]
        text_area.load_text("@")
        text_area.cursor_location = (0, 1)
        assert text_area._try_artifact_ref_completion() is True

        await pilot.press("enter")
        assert submitted == 1
        assert text_area.text == "@"
        assert text_area._file_completion_active is False

        assert text_area._try_artifact_ref_completion() is True
        await pilot.press("ctrl+l")
        assert submitted == 1
        assert text_area.text != "@"

        text_area.load_text("@")
        text_area.cursor_location = (0, 1)
        assert text_area._try_artifact_ref_completion() is True
        await pilot.press("ctrl+n", "enter")
        assert submitted == 1
        assert text_area.text != "@"


async def test_cold_path_snapshot_refreshes_the_open_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text("@src/")
        text_area.cursor_location = (0, 5)
        text_area._prompt_path_inflight.add(
            text_area._prompt_path_directory_key("src/")
        )

        assert text_area._try_artifact_ref_completion() is True
        assert isinstance(
            text_area._file_completion_candidates[0].metadata,
            AtReferenceLoadingCompletionMetadata,
        )
        directory_key = text_area._prompt_path_completion_directory_key
        assert directory_key is not None

        text_area._apply_prompt_path_inventory_result(
            _PromptPathInventoryWorkerResult(
                PromptPathSnapshot(
                    directory_key,
                    (PromptPathRow("main.py", False),),
                    (2, 2),
                ),
                changed=True,
            )
        )

        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@src/main.py"
        ]


async def test_vcs_tag_uses_target_project_catalog_for_dynamic_kind(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._xprompt_arg_hints.canonical_xprompt_project",
        lambda _project: "proj",
    )
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        catalog = replace(_CATALOG, project="proj")
        _seed_catalog(text_area, catalog, project="proj")
        text_area.load_text("#git:proj @des")
        text_area.cursor_location = (0, len(text_area.text))

        assert text_area._xprompt_arg_assist_project_from_text() == "proj"
        assert text_area._try_artifact_ref_completion() is True
        assert text_area._completion_kind == ARTIFACT_REF_COMPLETION_KIND
        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@designs:"
        ]


async def test_cold_catalog_schedules_warm_and_shows_loading_row() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("@pl")
        text_area.cursor_location = (0, 3)

        with patch.object(
            type(text_area),
            "_warm_current_artifact_ref_completion_catalog",
        ) as warm:
            assert text_area._try_artifact_ref_completion() is True

        warm.assert_called_once_with()
        assert text_area._file_completion_active is True
        assert isinstance(
            text_area._file_completion_candidates[0].metadata,
            AtReferenceLoadingCompletionMetadata,
        )


async def test_accept_kind_reopens_payload_then_accepts_document() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text("@pl")
        text_area.cursor_location = (0, 3)

        assert text_area._try_artifact_ref_completion() is True
        await pilot.press("enter")

        assert text_area.text == "@plans:"
        assert text_area._file_completion_active is True
        assert panel.border_title == "plans: documents"
        assert all(
            row.insertion.startswith("@plans:")
            for row in text_area._file_completion_candidates
        )

        await pilot.press("enter")
        assert text_area.text == "@plans:202607/alpha.md"
        assert text_area._file_completion_active is False


@pytest.mark.parametrize(
    ("token", "title", "expected"),
    (
        ("@plans:", "plans: documents", "@plans:202607/alpha.md"),
        ("@file:", "file: artifacts", "@file:explicit:abc123"),
        ("@chat:", "chat: chats", "@chat:202607/agent.md"),
        ("@commit:", "commit: commits", "@commit:sase@" + "a" * 40),
        ("@bug:", "bug: bugs", "@bug:sase#42"),
        ("@bead:", "bead: beads", "@bead:sase-9z"),
        ("@agent:", "agent: agents", "@agent:bbugyi200.athena.9w"),
    ),
)
async def test_all_payload_sources_render_stage_title_and_canonical_insertion(
    token: str,
    title: str,
    expected: str,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        panel = app.query_one("#prompt-completion", Static)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text(token)
        text_area.cursor_location = (0, len(token))

        with (
            patch.object(
                type(text_area),
                "_snapshot_artifact_ref_commit_candidates",
                return_value=(
                    ArtifactRefCommitCandidate("sase", "a" * 40, "Subject", 1),
                ),
            ),
            patch.object(
                type(text_area),
                "_snapshot_artifact_ref_bug_candidates",
                return_value=(ArtifactRefBugCandidate("sase", 42, "Issue"),),
            ),
        ):
            assert text_area._try_artifact_ref_completion() is True

        assert panel.border_title == title
        assert text_area._file_completion_candidates[0].insertion == expected
        assert isinstance(
            text_area._file_completion_candidates[0].metadata,
            ArtifactRefPayloadCompletionMetadata,
        )


async def test_mid_payload_accept_replaces_the_complete_detected_range() -> None:
    catalog = replace(
        _CATALOG,
        documents=(_ArtifactRefDocumentCandidate("plans", "202607/old.md", "Old"),),
    )
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, catalog)
        text_area.load_text("@plans:202607/olx.md after")
        text_area.cursor_location = (0, len("@plans:202607/ol"))

        await pilot.press("ctrl+t")
        assert text_area.text == "@plans:202607/old.md after"


async def test_refresh_preserves_selected_insertion_when_catalog_lands() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len(text_area.text))
        assert text_area._try_artifact_ref_completion(force=True) is True
        text_area._file_completion_index = 1

        refreshed = replace(
            _CATALOG,
            documents=(
                _ArtifactRefDocumentCandidate("plans", "202607/beta.md", "Beta"),
                _ArtifactRefDocumentCandidate("plans", "202607/bravo.md", "Bravo"),
            ),
        )
        _seed_catalog(text_area, refreshed)
        text_area._refresh_file_completion_from_cursor()

        assert (
            text_area._file_completion_candidates[
                text_area._file_completion_index
            ].insertion
            == "@plans:202607/beta.md"
        )


async def test_bare_at_claims_artifact_completion() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text("@")
        text_area.cursor_location = (0, 1)

        _seed_paths(text_area, "", ())
        assert text_area._try_artifact_ref_completion() is True
        assert text_area._file_completion_active is True


async def test_warm_keystroke_paths_do_not_touch_discovery_providers() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_catalog(text_area, _CATALOG)
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len(text_area.text))

        fail = AssertionError("keystroke path performed discovery")
        with (
            patch("sase.plan_search.facade.search", side_effect=fail),
            patch(
                "sase.core.artifact_file_query_facade.query_artifact_files",
                side_effect=fail,
            ),
            patch("sase.history.chat_storage.iter_chat_files", side_effect=fail),
            patch("subprocess.run", side_effect=fail),
        ):
            assert text_area._try_artifact_ref_completion(force=True) is True
            text_area._refresh_file_completion_from_cursor()
            assert text_area._accept_file_completion() is True

        assert text_area.text == "@plans:202607/beta.md"


def test_chat_catalog_scan_is_bounded(tmp_path) -> None:
    yielded = 0

    def _chat_files():
        nonlocal yielded
        for index in range(4):
            yielded += 1
            path = tmp_path / f"{index}.md"
            path.touch()
            yield path

    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path,
        artifact_index_path=tmp_path / "missing-index.jsonl",
        repositories=(),
        projects=(),
    )
    with (
        patch(
            "sase.history.chat_storage.iter_chat_files",
            return_value=_chat_files(),
        ),
        patch(
            "sase.ace.tui.widgets.artifact_ref_completion._MAX_CHAT_SCAN_ROWS",
            2,
        ),
        patch(
            "sase.ace.tui.widgets.artifact_ref_completion._MAX_CHAT_ROWS",
            2,
        ),
    ):
        catalog = load_artifact_ref_completion_catalog(None, context)

    assert yielded == 4
    assert len(catalog.chats) == 2
    assert catalog.payload_truncation["chat"] == 2


def test_artifact_index_cache_miss_queries_rust_and_reuses_unchanged_token(
    tmp_path,
) -> None:
    index = tmp_path / "index.jsonl"
    index.write_text("{}\n", encoding="utf-8")
    row = ArtifactFile(
        id="explicit:abc123",
        label="Diagram",
        kind="image",
        path="/stored/diagram.png",
    )
    resolved = index.resolve()
    _ARTIFACT_INDEX_CACHE.pop(resolved, None)

    with patch(
        "sase.core.artifact_file_query_facade.query_artifact_files",
        return_value=[row],
    ) as query:
        first = _read_cached_artifact_index(index)
        second = _read_cached_artifact_index(index)

    assert first == second == (row,)
    query.assert_called_once_with(resolved)


def test_artifact_file_catalog_preserves_rust_order_and_project_alias_filtering(
    tmp_path,
) -> None:
    def row(
        artifact_id: str,
        project: str | None,
    ) -> ArtifactFile:
        return ArtifactFile(
            id=artifact_id,
            label=artifact_id,
            kind="image",
            path=f"/stored/{artifact_id}.png",
            created_at="2026-07-29T12:00:00Z",
            project=project,
        )

    rust_ordered_rows = (
        row("explicit:aaa", None),
        row("explicit:bbb", "ss"),
        row("explicit:ignored", "other"),
        row("explicit:ccc", "gh_sase-org__sase"),
    )
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
                aliases=("ss",),
            ),
        ),
    )

    with patch(
        "sase.ace.tui.widgets.artifact_ref_completion._read_cached_artifact_index",
        return_value=rust_ordered_rows,
    ):
        candidates = _load_artifact_file_candidates("sase", context)

    assert [candidate.payload for candidate in candidates] == [
        "explicit:aaa",
        "explicit:bbb",
        "explicit:ccc",
    ]


def test_bead_catalog_caches_sorts_and_caps_rows(tmp_path) -> None:
    root = tmp_path / "beads"
    root.mkdir()
    (root / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    _BEAD_CACHE.pop(root.resolve(), None)
    issues = [
        Issue(
            id=f"sase-{index}",
            title=f"Issue {index}",
            status=Status.IN_PROGRESS,
            issue_type=IssueType.PLAN,
            tier=BeadTier.EPIC if index == 500 else BeadTier.PLAN,
            updated_at=f"2026-07-29T12:{index // 60:02d}:{index % 60:02d}Z",
        )
        for index in range(501)
    ]
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        bead_stores=(ArtifactRefBeadStore("sase", "sase", root),),
    )

    with patch(
        "sase.core.bead_read_facade.list_issues",
        return_value=issues,
    ) as list_rows:
        first = load_bead_candidates(context)
        second = load_bead_candidates(context)

    assert first == second
    assert len(first) == 500
    assert first[0].payload == "sase-500"
    assert first[0].detail == "in_progress · epic"
    list_rows.assert_called_once_with(root.resolve())


def test_agent_catalog_inserts_global_name_and_labels_current_owner(
    monkeypatch,
    tmp_path,
) -> None:
    agents_dir = tmp_path / "agents-root" / "agents"
    current = agents_dir / "bbugyi200.athena.9w"
    foreign = agents_dir / "alice.zeus.foo"
    current.mkdir(parents=True)
    foreign.mkdir()
    (current / "README.md").touch()
    (foreign / "README.md").touch()
    os.utime(current, (20, 20))
    os.utime(foreign, (10, 10))
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        agent_roots=(ArtifactRefAgentRoot("sase", tmp_path / "agents-root"),),
        agent_owner=ArtifactRefAgentOwner("bbugyi200", "athena"),
    )
    rows = load_agent_candidates(context)

    assert rows == (
        ArtifactRefAgentCandidate(
            payload="bbugyi200.athena.9w",
            label="9w",
            detail="sase",
            updated_at=20,
        ),
        ArtifactRefAgentCandidate(
            payload="alice.zeus.foo",
            label="alice.zeus.foo",
            detail="alice.zeus",
            updated_at=10,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._artifact_ref_entity_catalogs._MAX_ENTITY_ROWS",
        1,
    )
    assert load_agent_candidates(context) == rows[:1]
