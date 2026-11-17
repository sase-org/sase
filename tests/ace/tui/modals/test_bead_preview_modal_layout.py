"""Layout tests for the large bead preview card."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.bead_preview_modal import BeadPreviewModal
from sase.ace.tui.models.bead_preview import BeadPreview, BeadStoreRef
from sase.bead.model import BeadNote, BeadTier, Issue, IssueType, Status

_ROOT = Path(__file__).resolve().parents[4]
_PHASE_TITLES = tuple(
    f"Phase {index:02d}: {suffix}"
    for index, suffix in enumerate(
        (
            "mutation-path spike",
            "store wiring",
            "UI chrome",
            "undo path",
            "idempotency",
            "live enable",
            "verification",
            "docs pass",
            "screenshot goldens",
            "scroll keys",
            "footer pin",
            "separator width",
            "small-terminal fit",
            "wrap-up and sign-off",
        ),
        start=1,
    )
)
_LONG_DESCRIPTION = "\n\n".join(
    (
        "This epic owns the large bead-preview card: a 90% frame, a 1fr body, "
        "and a footer that stays pinned at every terminal size.",
        "The description is several paragraphs so the body overflows the "
        "enlarged frame on both a 200x60 terminal and a 100x30 terminal.",
        "Each paragraph restates the layout contract: 160x54 on a large "
        "terminal, 90x27 on a small one, and a full-width separator above "
        "the property grid.",
        "Extra lines keep the PHASES list from fitting without scroll: "
        + " ".join(f"line-{index}" for index in range(1, 40)),
    )
)


class _StyledBeadPreviewApp(App[None]):
    CSS_PATH = str(_ROOT / "src" / "sase" / "ace" / "tui" / "styles.tcss")

    def __init__(self, modal: BeadPreviewModal) -> None:
        super().__init__()
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal)


def _store(tmp_path: Path) -> BeadStoreRef:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir(exist_ok=True)
    return BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=beads_dir,
        primary_workspace=tmp_path,
    )


def _issue(**overrides: object) -> Issue:
    values: dict[str, object] = {
        "id": "sase-1aa",
        "title": "Epic title",
        "status": Status.IN_PROGRESS,
        "issue_type": IssueType.PLAN,
        "tier": BeadTier.EPIC,
        "description": "Epic body",
        "created_at": "2026-06-25T12:00:00+00:00",
        "updated_at": "2026-07-06T10:00:00+00:00",
    }
    values.update(overrides)
    return Issue(**values)  # type: ignore[arg-type]


def _short_preview(tmp_path: Path) -> BeadPreview:
    return BeadPreview(
        issue=_issue(
            title="Short task",
            status=Status.OPEN,
            issue_type=IssueType.TASK,
            tier=None,
            description="One-line description.",
        ),
        ancestors=(),
        children=(),
        depends_on=(),
        blocks=(),
        store=_store(tmp_path),
        plan_reference=None,
        plan_source="self",
        plan_path=None,
    )


def _long_epic_preview(tmp_path: Path) -> BeadPreview:
    children = tuple(
        _issue(
            id=f"sase-1aa.{index}",
            title=title,
            issue_type=IssueType.PHASE,
            tier=None,
            parent_id="sase-1aa",
            status=(
                Status.CLOSED,
                Status.IN_PROGRESS,
                Status.OPEN,
                Status.READY,
            )[(index - 1) % 4],
            size=("small", "medium", "large", "xsmall")[(index - 1) % 4],
            description=f"Phase {index} body.",
        )
        for index, title in enumerate(_PHASE_TITLES, start=1)
    )
    return BeadPreview(
        issue=_issue(
            title="Large bead preview card",
            description=_LONG_DESCRIPTION,
            notes=[
                BeadNote(
                    id="n1",
                    timestamp="2026-07-01T12:00:00+00:00",
                    author="bryan",
                    text="First note.",
                ),
                BeadNote(
                    id="n2",
                    timestamp="2026-07-04T12:00:00+00:00",
                    author="bryan",
                    text="Second note.",
                ),
            ],
        ),
        ancestors=(),
        children=children,
        depends_on=(),
        blocks=(),
        store=_store(tmp_path),
        plan_reference="bead_preview_large_card.md",
        plan_source="self",
        plan_path=str(tmp_path / "plans/202611/bead_preview_large_card.md"),
    )


def _footer_has_height(footer: Widget) -> bool:
    return footer.region.height > 0


async def _wait_for_card(
    pilot: object,
    modal: BeadPreviewModal,
) -> tuple[Container, VerticalScroll, Static]:
    footer = modal.query_one("#bead-preview-footer", Static)
    await wait_for(pilot, lambda: _footer_has_height(footer))
    container = modal.query_one("#bead-preview-container", Container)
    scroll = modal.query_one("#bead-preview-scroll", VerticalScroll)
    return container, scroll, footer


async def test_large_frame_on_a_big_terminal(tmp_path: Path) -> None:
    modal = BeadPreviewModal(
        _store(tmp_path),
        "sase-1aa",
        preview=_long_epic_preview(tmp_path),
    )
    app = _StyledBeadPreviewApp(modal)
    async with app.run_test(size=(200, 60)) as pilot:
        container, scroll, footer = await _wait_for_card(pilot, modal)
        assert container.region.size == (160, 54)
        assert footer.region.height > 0
        assert container.region.contains_region(footer.region)
        console = Console(
            width=max(scroll.region.width, 1),
            record=True,
            color_system=None,
            file=StringIO(),
        )
        console.print(modal._build_meta())
        rendered = console.export_text()
        phases_visible = all(title in rendered for title in _PHASE_TITLES)
        assert scroll.max_scroll_y > 0 or phases_visible


async def test_footer_survives_a_small_terminal(tmp_path: Path) -> None:
    modal = BeadPreviewModal(
        _store(tmp_path),
        "sase-1aa",
        preview=_long_epic_preview(tmp_path),
    )
    app = _StyledBeadPreviewApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        container, scroll, footer = await _wait_for_card(pilot, modal)
        assert container.region.size == (90, 27)
        assert footer.region.height > 0
        assert container.region.contains_region(footer.region)
        assert app.screen.region.contains_region(footer.region)
        assert scroll.max_scroll_y > 0


async def test_short_bead_still_uses_the_full_fixed_frame(tmp_path: Path) -> None:
    modal = BeadPreviewModal(
        _store(tmp_path),
        "sase-1aa",
        preview=_short_preview(tmp_path),
    )
    app = _StyledBeadPreviewApp(modal)
    async with app.run_test(size=(200, 60)) as pilot:
        container, _scroll, footer = await _wait_for_card(pilot, modal)
        assert container.region.size == (160, 54)
        assert footer.region.height > 0
        assert container.region.contains_region(footer.region)
        assert footer.region.bottom == container.content_region.bottom


async def test_separator_spans_the_console_width(tmp_path: Path) -> None:
    modal = BeadPreviewModal(
        _store(tmp_path),
        "sase-1aa",
        preview=_long_epic_preview(tmp_path),
    )
    console = Console(width=100, record=True, color_system=None, file=StringIO())
    console.print(modal._build_meta())
    lines = console.export_text().splitlines()
    assert "─" * 100 in lines
