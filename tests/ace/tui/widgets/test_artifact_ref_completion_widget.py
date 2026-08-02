"""Widget integration coverage for kind-tagged artifact completion."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.artifact_refs import parse_artifact_ref
from sase.ace.tui.widgets._file_completion_base import (
    _PromptCommitInventoryWorkerResult,
    _PromptPathInventoryWorkerResult,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefBugCandidate,
    ArtifactRefCommitCandidate,
    ArtifactRefPayloadCompletionMetadata,
    _ArtifactRefDocumentCandidate,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_commit_inventory import PromptCommitSnapshot
from sase.ace.tui.widgets.prompt_path_inventory import (
    PromptPathRow,
    PromptPathSnapshot,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._artifact_ref_completion_helpers import (
    CATALOG,
    seed_catalog,
    seed_paths,
)
from ._completion_helpers import CompletionTestApp


async def test_bare_at_opens_artifact_kinds_only() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        seed_paths(
            text_area,
            "",
            (PromptPathRow("src", True), PromptPathRow("Justfile", False)),
        )

        await pilot.press("@")

        assert text_area._completion_kind == ARTIFACT_REF_COMPLETION_KIND
        assert text_area._file_completion_active is True
        assert all(
            not isinstance(row.metadata, AtReferenceFileCompletionMetadata)
            for row in text_area._file_completion_candidates
        )
        assert text_area._artifact_ref_files_suppressed is True


async def test_ctrl_t_reveals_gated_files_before_accepting_lone_kind() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        seed_paths(
            text_area,
            "",
            (PromptPathRow("fixtures", True), PromptPathRow("final.txt", False)),
        )
        text_area.load_text("@f")
        text_area.cursor_location = (0, 2)

        await pilot.press("ctrl+t")

        assert text_area.text == "@f"
        assert text_area._artifact_ref_files_revealed is True
        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@file:",
            "@fixtures/",
            "@final.txt",
        ]

        await pilot.press("ctrl+t")

        assert text_area.text == "@file:"
        assert text_area._artifact_ref_files_revealed is False


async def test_revealed_files_survive_typing_and_reset_when_menu_closes() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        seed_paths(text_area, "", (PromptPathRow("final.txt", False),))
        text_area.load_text("@f")
        text_area.cursor_location = (0, 2)

        await pilot.press("ctrl+t", "i")

        assert text_area.text == "@fi"
        assert text_area._artifact_ref_files_revealed is True
        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@file:",
            "@final.txt",
        ]

        await pilot.press("ctrl+n", "enter")

        assert text_area.text == "@final.txt"
        assert text_area._file_completion_active is False
        assert text_area._artifact_ref_files_revealed is False


async def test_directory_accept_drills_down_and_file_accept_closes() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        seed_paths(text_area, "", (PromptPathRow("src", True),))
        seed_paths(text_area, "src/", (PromptPathRow("main.py", False),))
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
        seed_catalog(text_area, CATALOG)
        seed_paths(text_area, "", ())

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
        seed_catalog(text_area, CATALOG)
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


async def test_cold_commit_snapshot_loads_without_the_commits_pane() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area.load_text("@commit:")
        text_area.cursor_location = (0, len(text_area.text))
        text_area._prompt_commit_inflight.add(None)

        assert text_area._try_artifact_ref_completion() is True
        loading = text_area._file_completion_candidates[0]
        assert loading.display == "loading commits…"
        assert loading.insertion == ""
        assert isinstance(
            loading.metadata,
            AtReferenceLoadingCompletionMetadata,
        )

        text_area._prompt_commit_inflight.discard(None)
        text_area._apply_prompt_commit_inventory_result(
            _PromptCommitInventoryWorkerResult(
                PromptCommitSnapshot(
                    None,
                    (
                        ArtifactRefCommitCandidate(
                            "sase@" + "a" * 12,
                            "Pane-independent subject",
                            age="now",
                            scope="sase",
                            rank=0,
                        ),
                    ),
                    monotonic(),
                ),
                changed=True,
            )
        )

        candidate = text_area._file_completion_candidates[0]
        assert candidate.insertion == "@commit:sase@" + "a" * 12
        assert candidate.display == "sase@" + "a" * 12
        parsed = parse_artifact_ref(candidate.insertion.removeprefix("@"))
        assert parsed.payload.repo == "sase"
        assert parsed.payload.sha == "a" * 12
        metadata = candidate.metadata
        assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
        assert metadata.label == "Pane-independent subject"
        assert metadata.detail == ""
        assert metadata.age == "now"
        assert metadata.scope == "sase"
        assert metadata.rank == 0


async def test_commit_snapshot_scopes_to_the_prompt_target_project(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._xprompt_arg_hints.canonical_xprompt_project",
        lambda project: project,
    )
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, replace(CATALOG, project="proj"), project="proj")
        text_area._prompt_commit_snapshots[None] = PromptCommitSnapshot(
            None,
            (ArtifactRefCommitCandidate("wrong@" + "b" * 12, "Wrong"),),
            monotonic(),
        )
        text_area._prompt_commit_snapshots["proj"] = PromptCommitSnapshot(
            "proj",
            (
                ArtifactRefCommitCandidate(
                    "right@" + "c" * 12,
                    "Right",
                    scope="right",
                    rank=0,
                ),
            ),
            monotonic(),
        )
        text_area.load_text("#git:proj @commit:")
        text_area.cursor_location = (0, len(text_area.text))

        assert text_area._try_artifact_ref_completion() is True
        assert [row.insertion for row in text_area._file_completion_candidates] == [
            "@commit:right@" + "c" * 12
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
        catalog = replace(CATALOG, project="proj")
        seed_catalog(text_area, catalog, project="proj")
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
        seed_catalog(text_area, CATALOG)
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
        ("@commit:", "commit: commits", "@commit:sase@" + "a" * 12),
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
        seed_catalog(text_area, CATALOG)
        text_area._prompt_commit_snapshots[None] = PromptCommitSnapshot(
            None,
            (
                ArtifactRefCommitCandidate(
                    "sase@" + "a" * 12,
                    "Subject",
                    scope="sase",
                    rank=0,
                ),
            ),
            monotonic(),
        )
        text_area.load_text(token)
        text_area.cursor_location = (0, len(token))

        with patch.object(
            type(text_area),
            "_snapshot_artifact_ref_bug_candidates",
            return_value=(ArtifactRefBugCandidate("sase", 42, "Issue"),),
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
        CATALOG,
        documents=(_ArtifactRefDocumentCandidate("plans", "202607/old.md", "Old"),),
    )
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, catalog)
        text_area.load_text("@plans:202607/olx.md after")
        text_area.cursor_location = (0, len("@plans:202607/ol"))

        await pilot.press("ctrl+t")
        assert text_area.text == "@plans:202607/old.md after"


async def test_refresh_preserves_selected_insertion_when_catalog_lands() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len(text_area.text))
        assert text_area._try_artifact_ref_completion(force=True) is True
        text_area._file_completion_index = 1

        refreshed = replace(
            CATALOG,
            documents=(
                _ArtifactRefDocumentCandidate("plans", "202607/beta.md", "Beta"),
                _ArtifactRefDocumentCandidate("plans", "202607/bravo.md", "Bravo"),
            ),
        )
        seed_catalog(text_area, refreshed)
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
        seed_catalog(text_area, CATALOG)
        text_area.load_text("@")
        text_area.cursor_location = (0, 1)

        seed_paths(text_area, "", ())
        assert text_area._try_artifact_ref_completion() is True
        assert text_area._file_completion_active is True


async def test_warm_keystroke_paths_do_not_touch_discovery_providers() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
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
