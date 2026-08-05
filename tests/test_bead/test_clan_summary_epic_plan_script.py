"""Tests for authored-plan handling in the epic clan-summary script."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.bead.config import load_config
from sase.bead.model import BeadTier, IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.scripts.sase_clan_summary_epic import (
    _SUMMARY_MAX_UTF8_BYTES,
    _plan_bead_page_url,
    _plan_reference_candidates,
    _render_plan_summary,
    main,
)
from sase.sdd._plan_display_models import PlanProvenanceSection
from sase.sdd.plan_display import (
    COLOR_PLAN_PATH,
    COLOR_PLAN_PATH_BASENAME,
    PlanDisplay,
    PlanDisplayPhase,
)
from sase.sdd.plan_header_block import PlanHeaderSectionKind
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _write_epic_plan(
    path: Path,
    *,
    title: str,
    header: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = VALID_EPIC_PLAN.replace("Approved implementation", title)
    if header is not None:
        content = content.replace(
            "---\n# Plan",
            f"---\n\n{header}\n\n# Plan",
            1,
        )
    path.write_text(
        content,
        encoding="utf-8",
    )
    return path


def _patch_unexpected_bead_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_bead_load(_epic_id: str) -> None:
        raise AssertionError("a valid authored plan must bypass the bead store")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._load_epic_with_refresh",
        unexpected_bead_load,
    )


def test_epic_summary_renders_valid_environment_plan_before_bead_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_ref = "plans/authored[epic].md"
    plan = _write_epic_plan(tmp_path / plan_ref, title="Ship [safe] clan context")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-[epic]")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    _patch_unexpected_bead_load(monkeypatch)
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_bead_page_url",
        lambda _bead_id: (_ for _ in ()).throw(
            AssertionError("a plan without BEAD provenance must not resolve a page")
        ),
    )

    assert main() == 0

    captured = capsys.readouterr()
    markup = captured.out.rstrip("\n")
    rendered = Text.from_markup(markup)
    assert rendered.plain.splitlines()[0] == "◆ EPIC sase-[epic]"
    assert "▸ PLAN" not in rendered.plain
    assert "Title: Ship [safe] clan context" in rendered.plain
    assert "Goal: Deliver the approved implementation in ordered phases" in (
        rendered.plain
    )
    assert f"Path: {plan_ref}" in rendered.plain
    assert "implementation · no dependencies" in rendered.plain
    assert (
        "implementation: deliver and verify the approved implementation."
        in rendered.plain
    )
    assert "PHASES ·" not in rendered.plain
    assert "Page:" not in rendered.plain
    assert str(plan) not in rendered.plain
    assert "\\[epic]" in markup
    assert "\\[safe]" in markup
    assert all(cell_len(line) <= 76 for line in rendered.plain.splitlines())
    assert len(markup.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES
    assert captured.err == ""


def test_epic_summary_renders_counts_line_immediately_above_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_ref = "plans/counts-epic.md"
    _write_epic_plan(tmp_path / plan_ref, title="Counted epic")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-counts")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    lines = rendered.plain.splitlines()
    path_index = next(
        index for index, line in enumerate(lines) if line.startswith("   Path: ")
    )

    assert lines[path_index - 1] == " Counts: 1 phase · 1 wave"
    assert captured.err == ""


def test_plan_summary_renders_recorded_bead_page_after_bead_row() -> None:
    page_url = (
        "https://github.com/sase-org/sase--beads-with-a-long-repository-name/"
        "blob/main/pages/sase-ao/README.md"
    )
    summary = PlanDisplay(
        title="Hosted epic",
        goal="Open the durable bead page from the clan panel.",
        authored_tier="epic",
        effective_tier="epic",
        actual_path="/tmp/hosted.md",
        display_path="plans:202607/hosted.md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="available",
        phases=(),
        validation_ok=True,
        provenance=(
            PlanProvenanceSection(
                kind=PlanHeaderSectionKind.BEAD,
                entries=("sase-ao",),
                targets=(page_url,),
            ),
        ),
    )

    markup = _render_plan_summary(
        "sase-ao",
        summary,
        page_url=_plan_bead_page_url(summary),
    )
    rendered = Text.from_markup(markup)
    lines = rendered.plain.splitlines()
    bead_index = lines.index("   Bead: sase-ao")
    page_line = "   Page: " + page_url

    assert lines[bead_index + 1] == page_line
    assert rendered.plain.count(page_url) == 1
    assert cell_len(page_line) > 76
    assert all(cell_len(line) <= 76 for line in lines if line != page_line)

    console = Console()
    prefix_style = rendered.get_style_at_offset(
        console,
        rendered.plain.index("https://"),
    )
    basename_style = rendered.get_style_at_offset(
        console,
        rendered.plain.index("README.md"),
    )
    assert prefix_style == Style.parse(COLOR_PLAN_PATH)
    assert basename_style == Style.parse(COLOR_PLAN_PATH_BASENAME)


def test_plan_summary_resolves_bare_bead_provenance_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_ref = "plans/older-epic.md"
    _write_epic_plan(
        tmp_path / plan_ref,
        title="Older epic plan",
        header="- **BEAD:** sase-older",
    )
    page_url = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-older/README.md"
    )
    resolved_ids: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-older")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_bead_page_url",
        lambda bead_id: resolved_ids.append(bead_id) or page_url,
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    assert resolved_ids == ["sase-older"]
    rendered = Text.from_markup(captured.out)
    lines = rendered.plain.splitlines()
    bead_index = lines.index("   Bead: sase-older")
    assert lines[bead_index + 1] == "   Page: " + page_url
    assert captured.err == ""


def test_plan_summary_ignores_live_page_resolution_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_ref = "plans/older-epic.md"
    _write_epic_plan(
        tmp_path / plan_ref,
        title="Older epic plan",
        header="- **BEAD:** sase-older",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-older")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setattr(
        "sase.bead_pages.links.resolve_bead_page_url_from_cwd",
        lambda _bead_id: (_ for _ in ()).throw(RuntimeError("store unavailable")),
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert "   Bead: sase-older" in rendered.plain
    assert "Page:" not in rendered.plain
    assert captured.err == ""


def test_epic_summary_resolves_absolute_plan_reference_directly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _write_epic_plan(tmp_path / "absolute.md", title="Absolute source")
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-absolute")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", str(plan))
    snapshot = _write_epic_plan(tmp_path / "snapshot.md", title="Snapshot source")
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(snapshot))
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_primary_checkout",
        lambda: (_ for _ in ()).throw(
            AssertionError("absolute references must not resolve project metadata")
        ),
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert "Title: Absolute source" in rendered.plain
    assert "Title: Snapshot source" not in rendered.plain
    assert "Path: /" in rendered.plain
    assert plan.name in rendered.plain
    assert captured.err == ""


@pytest.mark.parametrize(
    ("current_title", "expected_title"),
    [("Current workspace plan", "Current workspace plan"), (None, "Primary plan")],
    ids=["current-workspace-precedence", "primary-checkout-fallback"],
)
def test_epic_summary_resolves_relative_plan_across_known_checkout_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    current_title: str | None,
    expected_title: str,
) -> None:
    launch = tmp_path / "launch"
    primary = tmp_path / "primary"
    launch.mkdir()
    primary.mkdir()
    plan_ref = "sase/repos/plans/202607/epic.md"
    _write_epic_plan(primary / plan_ref, title="Primary plan")
    snapshot = _write_epic_plan(tmp_path / "snapshot.md", title="Snapshot plan")
    if current_title is not None:
        _write_epic_plan(launch / plan_ref, title=current_title)

    monkeypatch.chdir(launch)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-roots")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(snapshot))

    def resolve_primary() -> Path:
        if current_title is not None:
            raise AssertionError(
                "a valid current-workspace plan must win before metadata lookup"
            )
        return primary

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_primary_checkout",
        resolve_primary,
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert f"Title: {expected_title}" in rendered.plain
    unexpected_title = (
        "Primary plan" if expected_title == "Current workspace plan" else None
    )
    if unexpected_title is not None:
        assert f"Title: {unexpected_title}" not in rendered.plain
    assert "Title: Snapshot plan" not in rendered.plain
    assert f"Path: {plan_ref}" in rendered.plain
    assert captured.err == ""


def test_epic_summary_uses_snapshot_when_checkout_candidates_are_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launch = tmp_path / "launch"
    primary = tmp_path / "primary"
    launch.mkdir()
    primary.mkdir()
    plan_ref = "sase/repos/plans/202607/epic.md"
    snapshot = _write_epic_plan(
        tmp_path / "state/projects/project/artifacts/epic-plans/sase-7.md",
        title="Race-free snapshot plan",
    )
    monkeypatch.chdir(launch)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-7")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(snapshot))
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_primary_checkout",
        lambda: primary,
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert "Title: Race-free snapshot plan" in rendered.plain
    assert "Goal: Deliver the approved implementation in ordered phases" in (
        rendered.plain
    )
    assert "implementation · no dependencies" in rendered.plain
    assert f"Path: {plan_ref}" in rendered.plain
    assert str(snapshot) not in rendered.plain
    assert captured.err == ""


def test_plan_reference_candidates_deduplicate_absolute_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "epic.md"
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(plan))

    assert list(_plan_reference_candidates(str(plan))) == [plan.resolve()]


@pytest.mark.parametrize("kind", ["missing", "unreadable", "invalid"])
def test_unusable_plan_reference_falls_back_to_legacy_bead_summary(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Stable bead fallback",
            IssueType.PLAN,
            description="Keep the established fallback shape.",
            tier=BeadTier.EPIC,
        )
        project.create(
            "Legacy fallback phase",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.MEDIUM,
        )

    plan_ref = f"{kind}.md"
    snapshot = project_dir / "state" / f"{kind}.md"
    snapshot.parent.mkdir()
    if kind == "unreadable":
        (project_dir / plan_ref).write_bytes(b"\xff\xfe")
        snapshot.write_bytes(b"\xff\xfe")
    elif kind == "invalid":
        (project_dir / plan_ref).write_text(
            "---\ntier: epic\ntitle: Invalid\n---\n# Plan\n",
            encoding="utf-8",
        )
        snapshot.write_text(
            "---\ntier: epic\ntitle: Invalid snapshot\n---\n# Plan\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("SASE_CLAN_NAME", epic.id)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(snapshot))

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert rendered.plain.splitlines()[0] == (
        f"◆ EPIC {epic.id} · Stable bead fallback · ⧖ now"
    )
    assert "PHASES · 0/1 done at launch" in rendered.plain
    assert "○ 1. Legacy fallback phase" in rendered.plain
    assert captured.err == ""


def test_plan_and_bead_failure_emit_diagnostics_and_safe_identity_fallback(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id = "missing[epic]"
    plan_ref = "missing[plan].md"
    snapshot = project_dir / "private-state" / "missing-snapshot.md"
    monkeypatch.setenv("SASE_CLAN_NAME", epic_id)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", str(snapshot))
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "off",
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing\\[epic][/]\n"
    assert Text.from_markup(captured.out).plain == f"EPIC {epic_id}\n"
    assert "Unable to load epic clan summary for 'missing[epic]'" in captured.err
    assert f"Plan reference {plan_ref!r} was also unavailable" in captured.err
    assert "plan file does not exist" in captured.err
    assert "epic plan snapshot" in captured.err
    assert str(snapshot) not in captured.err
    assert "Traceback (most recent call last):" in captured.err


def test_plan_summary_omits_only_complete_tail_phase_blocks_within_budget() -> None:
    phases = tuple(
        PlanDisplayPhase(
            id=f"phase-{index}",
            title=f"Phase {index} " + "界 roadmap " * 8,
            depends_on=((f"phase-{index - 1}",) if index > 1 else ()),
            description=(
                f"Phase {index} description preserves [literal] markup and the "
                "complete plan block."
            ),
            size=("small", "medium", "large")[(index - 1) % 3],
            model="codex/gpt-5.6-sol",
        )
        for index in range(1, 1001)
    )
    summary = PlanDisplay(
        title="Large authored epic",
        goal="Retain complete leading fields and whole phase blocks.",
        authored_tier="epic",
        effective_tier="epic",
        actual_path="/tmp/large.md",
        display_path="plans/large[epic].md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="available",
        phases=phases,
        validation_ok=True,
    )

    markup = _render_plan_summary("sase-large[epic]", summary)
    rendered = Text.from_markup(markup)

    assert len(markup.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES
    assert "Counts: 1000 phases · 1000 waves" in rendered.plain
    omission = re.search(
        r"… (\d+) phase blocks omitted to fit summary size",
        rendered.plain,
    )
    assert omission is not None
    omitted = int(omission.group(1))
    included = len(phases) - omitted
    assert included > 0
    assert f"phase-{included} ·" in rendered.plain
    assert f"Phase {included} description" in rendered.plain
    assert f"phase-{included + 1} ·" not in rendered.plain
    assert f"Phase {included + 1} description" not in rendered.plain
    assert all(cell_len(line) <= 76 for line in rendered.plain.splitlines())
