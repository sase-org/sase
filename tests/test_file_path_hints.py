"""Tests for file path detection and hint rendering in agent displays."""

from unittest.mock import Mock

import pytest
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_LINES
from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
    _FILE_PATH_RE,
    append_text_with_file_hints,
    iter_container_file_path_matches,
    iter_file_path_matches,
    resolve_agent_workspace_dir,
    resolve_file_path,
)
from sase.ace.tui.widgets.prompt_panel._hint_caps import (
    HINT_TRUNCATION_MESSAGE,
    HintContentBudget,
    append_bounded_text_with_file_hints,
    bound_hint_content,
)


# --- Tests for _FILE_PATH_RE ---


def test_regex_matches_dot_directory_path() -> None:
    """Match .sase/foo/bar.diff style paths."""
    m = _FILE_PATH_RE.search("see the .sase/xcmds/foo.diff file")
    assert m is not None
    assert m.group(2) == ".sase/xcmds/foo.diff"


def test_regex_matches_at_prefixed_path() -> None:
    """Match @.sase/foo/bar.diff with @ as group 1."""
    m = _FILE_PATH_RE.search("see @.sase/xcmds/foo.diff file")
    assert m is not None
    assert m.group(1) == "@"
    assert m.group(2) == ".sase/xcmds/foo.diff"


def test_regex_matches_absolute_path() -> None:
    """Match absolute paths like /home/user/file.py."""
    m = _FILE_PATH_RE.search("open /home/user/file.py now")
    assert m is not None
    assert m.group(2) == "/home/user/file.py"


def test_regex_matches_home_relative_path() -> None:
    """Match ~/Documents/file.txt paths."""
    m = _FILE_PATH_RE.search("see ~/Documents/file.txt here")
    assert m is not None
    assert m.group(2) == "~/Documents/file.txt"


def test_regex_matches_dot_slash_relative_path() -> None:
    """Match ./relative/path.py paths."""
    m = _FILE_PATH_RE.search("use ./src/main.py")
    assert m is not None
    assert m.group(2) == "./src/main.py"


def test_regex_matches_dotdot_relative_path() -> None:
    """Match ../parent/path.py paths."""
    m = _FILE_PATH_RE.search("see ../parent/file.py")
    assert m is not None
    assert m.group(2) == "../parent/file.py"


def test_regex_matches_bare_relative_with_extension() -> None:
    """Match bare relative paths like src/main.py (require extension)."""
    m = _FILE_PATH_RE.search("edit src/main.py")
    assert m is not None
    assert m.group(2) == "src/main.py"


def test_regex_no_match_bare_relative_without_extension() -> None:
    """Don't match bare relative paths without extension."""
    m = _FILE_PATH_RE.search("see the commit/fix here")
    assert m is None


def test_regex_no_match_plain_text() -> None:
    """Don't match plain text without path patterns."""
    m = _FILE_PATH_RE.search("just some regular text")
    assert m is None


def test_regex_stops_at_space() -> None:
    """Path matching stops at whitespace."""
    m = _FILE_PATH_RE.search("@.sase/foo.diff file)")
    assert m is not None
    assert m.group(2) == ".sase/foo.diff"


def test_regex_stops_at_paren() -> None:
    """Path matching stops at parentheses."""
    m = _FILE_PATH_RE.search("(@.sase/foo.diff)")
    assert m is not None
    assert m.group(2) == ".sase/foo.diff"


def test_regex_no_match_inside_word() -> None:
    """Don't match when preceded by word character."""
    m = _FILE_PATH_RE.search("hello@.sase/foo.diff")
    assert m is None


def test_regex_matches_multiple_paths() -> None:
    """Find multiple file paths in one string."""
    text = "see /path/a.py and src/b.txt for details"
    matches = list(_FILE_PATH_RE.finditer(text))
    assert len(matches) == 2
    assert matches[0].group(2) == "/path/a.py"
    assert matches[1].group(2) == "src/b.txt"


def test_container_matcher_keeps_plans_prefix_isolated() -> None:
    """Only container hint matching treats ``plan:`` as part of the token."""
    content = "Plan: plan:202608/clan.md"

    generic = list(iter_file_path_matches(content))
    container = list(iter_container_file_path_matches(content))

    assert [match.group(2) for match in generic] == ["202608/clan.md"]
    assert [match.group(2) for match in container] == ["plan:202608/clan.md"]


# --- Tests for append_text_with_file_hints ---


def test_append_no_paths() -> None:
    """Text without file paths is appended unchanged."""
    text = Text()
    counter = append_text_with_file_hints(text, "just plain text\n", 1, {}, None)
    assert counter == 1
    assert text.plain == "just plain text\n"


def test_append_with_one_path() -> None:
    """Single file path gets a [1] hint marker."""
    text = Text()
    mappings: dict[int, str] = {}
    counter = append_text_with_file_hints(
        text,
        "see @.sase/foo.diff here",
        1,
        mappings,
        "/workspace",
    )
    assert counter == 2
    assert "[1] " in text.plain
    assert "@.sase/foo.diff" in text.plain
    assert mappings[1] == "/workspace/.sase/foo.diff"


def test_append_resolves_absolute_path() -> None:
    """Absolute paths are stored as-is in mappings."""
    text = Text()
    mappings: dict[int, str] = {}
    append_text_with_file_hints(
        text,
        "see /absolute/path.py here",
        1,
        mappings,
        "/workspace",
    )
    assert mappings[1] == "/absolute/path.py"


def test_append_resolves_home_path() -> None:
    """Home-relative paths are expanded."""
    text = Text()
    mappings: dict[int, str] = {}
    append_text_with_file_hints(
        text,
        "see ~/docs/file.txt here",
        1,
        mappings,
        "/workspace",
    )
    # Should be expanded via os.path.expanduser
    assert "~" not in mappings[1]
    assert mappings[1].endswith("/docs/file.txt")


def test_append_multiple_paths_increment_counter() -> None:
    """Multiple paths get sequential hint numbers."""
    text = Text()
    mappings: dict[int, str] = {}
    counter = append_text_with_file_hints(
        text,
        "see /a.py and /b.py",
        1,
        mappings,
        None,
    )
    assert counter == 3
    assert 1 in mappings
    assert 2 in mappings
    assert "[1] " in text.plain
    assert "[2] " in text.plain


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_append_skips_paths_contained_in_http_urls(scheme: str) -> None:
    """Path-shaped URL suffixes stay plain while real paths get hints."""
    url = (
        f"{scheme}://github.com/sase-org/sase--beads/blob/main/pages/sase-d9/README.md"
    )
    text = Text()
    mappings: dict[int, str] = {}

    counter = append_text_with_file_hints(
        text,
        f"Read {url}, then open docs/local.md.",
        1,
        mappings,
        "/workspace",
    )

    assert counter == 2
    assert text.plain == f"Read {url}, then open [1] docs/local.md."
    assert mappings == {1: "/workspace/docs/local.md"}


def test_append_continues_from_given_counter() -> None:
    """Hint counter starts from the provided value."""
    text = Text()
    mappings: dict[int, str] = {}
    counter = append_text_with_file_hints(
        text,
        "see /a.py here",
        5,
        mappings,
        None,
    )
    assert counter == 6
    assert 5 in mappings
    assert "[5] " in text.plain


def test_append_relative_path_no_workspace() -> None:
    """Relative paths without workspace_dir use abspath fallback."""
    text = Text()
    mappings: dict[int, str] = {}
    append_text_with_file_hints(
        text,
        "see src/main.py here",
        1,
        mappings,
        None,
    )
    # Should be an absolute path (via os.path.abspath)
    assert mappings[1].startswith("/")
    assert mappings[1].endswith("src/main.py")


def test_bounded_append_omits_tail_hints_without_renumbering_head() -> None:
    """Only the retained prefix is scanned and its numbering stays stable."""
    content = "\n".join(
        [
            "see src/head.py",
            *(f"plain line {index}" for index in range(PLAIN_RENDER_MAX_LINES)),
            "see src/tail.py",
        ]
    )
    text = Text()
    mappings: dict[int, str] = {}

    counter = append_bounded_text_with_file_hints(
        text,
        content,
        7,
        mappings,
        "/workspace",
    )

    assert counter == 8
    assert mappings == {7: "/workspace/src/head.py"}
    assert "[7] src/head.py" in text.plain
    assert "src/tail.py" not in text.plain
    assert HINT_TRUNCATION_MESSAGE in text.plain


def test_bounded_append_drops_path_cut_by_byte_cap() -> None:
    """A byte boundary cannot turn a path prefix into a different mapping."""
    prefix = "x" * 127_990
    content = f"{prefix} src/path-that-crosses-the-byte-limit.py"
    text = Text()
    mappings: dict[int, str] = {}

    counter = append_bounded_text_with_file_hints(
        text,
        content,
        1,
        mappings,
        "/workspace",
    )

    assert counter == 1
    assert mappings == {}
    assert HINT_TRUNCATION_MESSAGE in text.plain


def test_container_bound_content_drops_partial_logical_plan_reference() -> None:
    """A byte cap cannot leave ``plan:`` detached from its path."""
    content = "Open plan:202608/clan.md after approval"

    bounded = bound_hint_content(
        content,
        budget=HintContentBudget(
            remaining_bytes=len("Open plan:"),
            remaining_lines=10,
        ),
        matcher=iter_container_file_path_matches,
    )

    assert bounded.content == "Open "
    assert "plan:" not in bounded.content
    assert bounded.notice is not None


def test_workspace_resolution_is_memoized_by_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    """Repeated render fragments do not repeat project/workspace disk work."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_file = str(tmp_path / "project.sase")
    detect = Mock(return_value="git")
    parse = Mock(return_value=str(tmp_path))
    get_workspace = Mock(return_value=str(workspace))
    monkeypatch.setattr("sase.workspace_provider.detect_workflow_type", detect)
    monkeypatch.setattr("sase.workspace_provider.utils.parse_workspace_dir", parse)
    monkeypatch.setattr(
        "sase.workspace_provider.get_workspace_directory",
        get_workspace,
    )
    resolve_agent_workspace_dir.cache_clear()

    first = resolve_agent_workspace_dir(21, project_file, None)
    second = resolve_agent_workspace_dir(21, project_file, None)

    assert first == second == str(workspace)
    detect.assert_called_once_with(project_file)
    parse.assert_called_once_with(project_file)
    get_workspace.assert_called_once()


def test_file_path_resolution_is_memoized_by_inputs(monkeypatch) -> None:
    """Repeated matches of one path reuse the resolved absolute path."""
    expanduser = Mock(side_effect=lambda path: path)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._file_path_hints.os.path.expanduser",
        expanduser,
    )
    resolve_file_path.cache_clear()

    assert resolve_file_path("src/main.py", "/workspace") == ("/workspace/src/main.py")
    assert resolve_file_path("src/main.py", "/workspace") == ("/workspace/src/main.py")
    expanduser.assert_called_once_with("src/main.py")
