"""Panel rendering coverage for the ``@<kind>::`` ref-sync gesture."""

from __future__ import annotations

from rich.text import Text

from sase.artifact_ref_sync import ArtifactRefSyncPlan
from sase.ace.tui.widgets._artifact_ref_sync import ArtifactRefSyncMixin, _RefSyncState
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    artifact_ref_completion_subtitle,
    completion_panel_title,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_artifacts import (
    _ARTIFACT_SOURCE_BADGES,
    _NEW_PAYLOAD_BADGE,
    append_artifact_ref_completion_row,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._artifact_ref_completion_helpers import CATALOG, seed_catalog
from ._completion_helpers import CompletionTestApp

_PLAN = ArtifactRefSyncPlan(
    kind="plans", mode="pull", role="plans", label="sase--plans", checkout=None
)


def _row_for(
    project: str | None, kind: str, mixin: ArtifactRefSyncMixin
) -> CompletionCandidate:
    row = mixin._artifact_ref_sync_row(project, kind)
    assert row is not None
    return row


class _Host(ArtifactRefSyncMixin):
    """Bare host exercising the mixin's pure row builder without Textual."""

    def __init__(self) -> None:
        self._artifact_ref_sync_states: dict[tuple[str | None, str], _RefSyncState] = {}
        self._artifact_ref_sync_spinner_timer = None


def test_running_row_says_syncing_for_pull_mode() -> None:
    host = _Host()
    host._artifact_ref_sync_states[(None, "plans")] = _RefSyncState(
        phase="running", plan=_PLAN
    )

    row = _row_for(None, "plans", host)

    assert row.display == "syncing sase--plans …"
    assert isinstance(row.metadata, ArtifactRefSyncCompletionMetadata)
    assert row.metadata.phase == "running"
    assert row.metadata.kind == "plans"


def test_running_row_says_cloning_for_clone_mode() -> None:
    host = _Host()
    clone_plan = ArtifactRefSyncPlan(
        kind="research",
        mode="clone",
        role="research",
        label="sase--research",
        checkout=None,
    )
    host._artifact_ref_sync_states[(None, "research")] = _RefSyncState(
        phase="running", plan=clone_plan
    )

    row = _row_for(None, "research", host)

    assert row.display == "cloning sase--research …"


def test_settled_ok_row_reports_new_payload_count() -> None:
    host = _Host()
    host._artifact_ref_sync_states[(None, "plans")] = _RefSyncState(
        phase="settled_ok",
        plan=_PLAN,
        new_payloads=frozenset({"a", "b"}),
    )

    row = _row_for(None, "plans", host)

    assert row.display == "sase--plans synced · 2 new"
    assert row.metadata.phase == "settled_ok"


def test_settled_error_row_carries_detail() -> None:
    host = _Host()
    host._artifact_ref_sync_states[(None, "plans")] = _RefSyncState(
        phase="settled_error", plan=_PLAN, detail="could not reach origin"
    )

    row = _row_for(None, "plans", host)

    assert row.display == "sase--plans sync failed"
    assert row.metadata.phase == "settled_error"
    assert row.metadata.detail == "could not reach origin"


def test_spinner_tick_advances_frame_and_stops_when_idle() -> None:
    host = _Host()
    host._file_completion_active = False
    host._completion_kind = "file"
    host._file_completion_candidates = []
    host._artifact_ref_sync_states[(None, "plans")] = _RefSyncState(
        phase="running", plan=_PLAN
    )

    host._tick_artifact_ref_sync_spinner()

    assert host._artifact_ref_sync_states[(None, "plans")].frame == 1
    assert (
        host._artifact_ref_sync_spinner_timer is None
    )  # never started via set_interval here

    host._artifact_ref_sync_states.clear()
    stopped: list[bool] = []
    host._stop_artifact_ref_sync_spinner = lambda: stopped.append(True)  # type: ignore[method-assign]
    host._tick_artifact_ref_sync_spinner()
    assert stopped == [True]


def test_badges_are_all_four_cells_wide() -> None:
    for badge, _style in (*_ARTIFACT_SOURCE_BADGES.values(), _NEW_PAYLOAD_BADGE):
        assert Text(badge).cell_len == 4


def test_new_payload_row_renders_the_new_badge_instead_of_source_badge() -> None:
    content = Text()
    candidate = CompletionCandidate(
        display="202608/new.md",
        insertion="@plans:202608/new.md",
        is_dir=False,
        name="202608/new.md",
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="plans", payload="202608/new.md", source="document", is_new=True
        ),
    )

    append_artifact_ref_completion_row(content, candidate, False)

    assert content.plain.startswith("[✦] ")


def test_ordinary_payload_row_keeps_its_source_badge() -> None:
    content = Text()
    candidate = CompletionCandidate(
        display="202607/alpha.md",
        insertion="@plans:202607/alpha.md",
        is_dir=False,
        name="202607/alpha.md",
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="plans", payload="202607/alpha.md", source="document"
        ),
    )

    append_artifact_ref_completion_row(content, candidate, False)

    assert content.plain.startswith("[D] ")


def test_sync_row_renders_dim_status_line() -> None:
    content = Text()
    candidate = CompletionCandidate(
        display="syncing sase--plans …",
        insertion="",
        is_dir=False,
        name="",
        metadata=ArtifactRefSyncCompletionMetadata(
            kind="plans", phase="running", label="syncing sase--plans …", frame=2
        ),
    )

    append_artifact_ref_completion_row(content, candidate, False)

    assert "syncing sase--plans" in content.plain


def test_title_reports_kind_and_status() -> None:
    rows = [
        CompletionCandidate(
            display="syncing sase--plans …",
            insertion="",
            is_dir=False,
            name="",
            metadata=ArtifactRefSyncCompletionMetadata(
                kind="plans", phase="running", label="syncing sase--plans …"
            ),
        )
    ]
    kinds = CompletionPanelKinds.classify(ARTIFACT_REF_COMPLETION_KIND, rows)

    title = completion_panel_title(kinds, "plans", rows, "")

    assert title == "@ plans · syncing"


def test_title_reports_synced_and_failed_status() -> None:
    for phase, expected in (("settled_ok", "synced"), ("settled_error", "sync failed")):
        rows = [
            CompletionCandidate(
                display="x",
                insertion="",
                is_dir=False,
                name="",
                metadata=ArtifactRefSyncCompletionMetadata(
                    kind="plans", phase=phase, label="x"
                ),
            )
        ]
        kinds = CompletionPanelKinds.classify(ARTIFACT_REF_COMPLETION_KIND, rows)

        assert (
            completion_panel_title(kinds, "plans", rows, "") == f"@ plans · {expected}"
        )


def test_subtitle_prepends_sync_segment_when_it_fits() -> None:
    rows = [
        CompletionCandidate(
            display="x",
            insertion="",
            is_dir=False,
            name="",
            metadata=ArtifactRefSyncCompletionMetadata(
                kind="plans", phase="running", label="x"
            ),
        )
    ]

    subtitle = artifact_ref_completion_subtitle(rows, 2, 2, 0, 200)

    assert "syncing" in subtitle.plain


def test_subtitle_drops_sync_segment_first_when_narrow() -> None:
    rows = [
        CompletionCandidate(
            display="x",
            insertion="",
            is_dir=False,
            name="",
            metadata=ArtifactRefSyncCompletionMetadata(
                kind="plans", phase="running", label="x"
            ),
        )
    ]

    wide = artifact_ref_completion_subtitle(rows, 2, 2, 0, 200)
    narrow = artifact_ref_completion_subtitle(rows, 2, 2, 0, wide.cell_len - 1)

    assert "syncing" not in narrow.plain
    assert "2 of 2" in narrow.plain


async def test_sync_row_is_never_selectable_via_index_or_navigation() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area._artifact_ref_sync_states[(None, "plans")] = _RefSyncState(
            phase="running", plan=_PLAN
        )
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len("@plans:"))

        assert text_area._try_artifact_ref_completion() is True
        assert isinstance(
            text_area._file_completion_candidates[0].metadata,
            ArtifactRefSyncCompletionMetadata,
        )
        # Seeded at the first *selectable* row, skipping the pinned sync row.
        assert text_area._file_completion_index != 0

        # Force the index onto the sync row and confirm accepting is a no-op.
        text_area._file_completion_index = 0
        before = text_area.text
        assert text_area._accept_file_completion() is False
        assert text_area.text == before
