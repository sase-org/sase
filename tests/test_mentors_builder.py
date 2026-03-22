"""Tests for the MENTORS section builder hint support."""

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommitEntry, MentorEntry, MentorStatusLine
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.hint_tracker import HintTracker
from sase.ace.tui.widgets.mentors_builder import build_mentors_section
from rich.text import Text


def _make_changespec(
    name: str = "test_feature",
    commits: list[CommitEntry] | None = None,
    mentors: list[MentorEntry] | None = None,
) -> ChangeSpec:
    """Create a minimal ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        commits=commits,
        mentors=mentors,
    )


def _make_hint_tracker(counter: int = 0) -> HintTracker:
    """Create a fresh HintTracker for testing."""
    return HintTracker(
        counter=counter,
        mappings={},
        hook_hint_to_idx={},
        hint_to_entry_id={},
        mentor_hint_to_info={},
    )


@patch("sase.ace.tui.widgets.mentors_builder.os.path.exists", return_value=True)
@patch(
    "sase.ace.display_helpers.format_profile_with_count",
    return_value="prof[1/1]",
)
def test_commented_status_displayed(_mock_fmt: object, _mock_exists: object) -> None:
    """Test that COMMENTED status is displayed with proper styling."""
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="code_quality",
        status="COMMENTED",
        timestamp="260321_120000",
        duration="3m15s",
    )
    mentor_entry = MentorEntry(
        entry_id="1",
        profiles=["prof"],
        status_lines=[msl],
    )
    changespec = _make_changespec(
        commits=[CommitEntry(number=1, note="initial")],
        mentors=[mentor_entry],
    )

    text = Text()
    tracker = build_mentors_section(
        text,
        changespec,
        mentors_fold=FoldLevel.EXPANDED,
        with_hints=True,
        hint_tracker=_make_hint_tracker(counter=0),
    )

    plain = text.plain
    assert "COMMENTED" in plain
    assert "3m15s" in plain
    # COMMENTED should get a hint (like PASSED/FAILED)
    assert tracker.counter == 1


@patch("sase.ace.tui.widgets.mentors_builder.os.path.exists", return_value=True)
@patch(
    "sase.ace.display_helpers.format_profile_with_count",
    return_value="prof[1/1]",
)
def test_commented_shown_in_collapsed_mode(
    _mock_fmt: object, _mock_exists: object
) -> None:
    """Test that COMMENTED is shown (not folded) in COLLAPSED mode for latest entry."""
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="code_quality",
        status="COMMENTED",
        timestamp="260321_120000",
        duration="3m15s",
    )
    mentor_entry = MentorEntry(
        entry_id="1",
        profiles=["prof"],
        status_lines=[msl],
    )
    changespec = _make_changespec(
        commits=[CommitEntry(number=1, note="initial")],
        mentors=[mentor_entry],
    )

    text = Text()
    build_mentors_section(
        text,
        changespec,
        mentors_fold=FoldLevel.COLLAPSED,
        with_hints=False,
        hint_tracker=_make_hint_tracker(),
    )

    plain = text.plain
    # COMMENTED should be visible in COLLAPSED mode (like FAILED), not folded
    assert "COMMENTED" in plain
    assert "folded" not in plain


@patch("sase.ace.tui.widgets.mentors_builder.os.path.exists", return_value=True)
@patch(
    "sase.ace.display_helpers.format_profile_with_count",
    return_value="prof[1/1]",
)
def test_error_non_path_suffix_no_hint(_mock_fmt: object, _mock_exists: object) -> None:
    """Error suffix that is NOT a file path does not get a hint."""
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="fixit_wells",
        status="FAILED",
        timestamp="260206_100530",
        duration="0h1m30s",
        suffix="Connection error",
        suffix_type="error",
    )
    mentor_entry = MentorEntry(
        entry_id="3",
        profiles=["prof"],
        status_lines=[msl],
    )
    changespec = _make_changespec(
        commits=[CommitEntry(number=3, note="current")],
        mentors=[mentor_entry],
    )

    text = Text()
    tracker = build_mentors_section(
        text,
        changespec,
        mentors_fold=FoldLevel.FULLY_EXPANDED,
        with_hints=True,
        hint_tracker=_make_hint_tracker(counter=5),
    )

    # Hint 5 is for the chat path (FAILED status line), no extra hint for the error suffix
    assert tracker.counter == 6
    # The error text should appear but without a hint number for it
    plain = text.plain
    assert "Connection error" in plain


@patch(
    "sase.ace.display_helpers.format_profile_with_count",
    return_value="prof[1/1]",
)
def test_error_file_path_no_hint_without_with_hints(_mock_fmt: object) -> None:
    """Error file path suffix does NOT get a hint when with_hints=False."""
    error_path = "~/.sase/mentors/fixit_wells-260206_100530.txt"
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="fixit_wells",
        status="FAILED",
        timestamp="260206_100530",
        duration="0h1m30s",
        suffix=error_path,
        suffix_type="error",
    )
    mentor_entry = MentorEntry(
        entry_id="3",
        profiles=["prof"],
        status_lines=[msl],
    )
    changespec = _make_changespec(
        commits=[CommitEntry(number=3, note="current")],
        mentors=[mentor_entry],
    )

    text = Text()
    tracker = build_mentors_section(
        text,
        changespec,
        mentors_fold=FoldLevel.FULLY_EXPANDED,
        with_hints=False,
        hint_tracker=_make_hint_tracker(counter=0),
    )

    # No hints should be generated when with_hints=False
    assert tracker.counter == 0
    assert len(tracker.mappings) == 0


@patch("sase.ace.tui.widgets.mentors_builder.os.path.exists", return_value=True)
@patch(
    "sase.ace.display_helpers.format_profile_with_count",
    return_value="prof[1/1]",
)
def test_error_absolute_path_suffix_gets_hint(
    _mock_fmt: object, _mock_exists: object
) -> None:
    """Error suffix with absolute path (starting with /) gets a hint."""
    error_path = "/home/user/.sase/mentors/fixit_wells-260206_100530.txt"
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="fixit_wells",
        status="FAILED",
        timestamp="260206_100530",
        duration="0h1m30s",
        suffix=error_path,
        suffix_type="error",
    )
    mentor_entry = MentorEntry(
        entry_id="3",
        profiles=["prof"],
        status_lines=[msl],
    )
    changespec = _make_changespec(
        commits=[CommitEntry(number=3, note="current")],
        mentors=[mentor_entry],
    )

    text = Text()
    tracker = build_mentors_section(
        text,
        changespec,
        mentors_fold=FoldLevel.FULLY_EXPANDED,
        with_hints=True,
        hint_tracker=_make_hint_tracker(counter=0),
    )

    # Hint 0 is the chat path, hint 1 is the error file path
    assert 1 in tracker.mappings
    assert tracker.mappings[1] == error_path
    assert tracker.counter == 2
