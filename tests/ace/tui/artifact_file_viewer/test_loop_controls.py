from __future__ import annotations

from sase.ace.tui.graphics import _viewer_loop
from sase.ace.tui.graphics.viewer import (
    _print_page_prompt,
    page_index_after_key,
    page_loop_available_keys,
)

from ._helpers import _strip_ansi


def test_artifact_page_index_state_machine() -> None:
    assert page_index_after_key(0, "j", 3) == 1
    assert page_index_after_key(2, "j", 3) == 0
    assert page_index_after_key(2, "k", 3) == 1
    assert page_index_after_key(0, "k", 3) == 2
    assert page_index_after_key(0, "n", 3) == 0
    assert page_index_after_key(2, "p", 3) == 2
    assert page_index_after_key(1, "r", 3) == 1
    assert page_index_after_key(1, "z", 3) == 1
    assert page_index_after_key(1, "x", 3) == 1
    assert page_index_after_key(0, "q", 3) is None
    assert page_index_after_key(0, "j", 1) == 0
    assert page_index_after_key(0, "k", 1) == 0


def test_artifact_page_loop_available_keys_and_prompts(capsys) -> None:
    assert page_loop_available_keys(0, 1) == ("r", "q")
    assert page_loop_available_keys(0, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(1, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(2, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(1, 3, artifact_index=1, artifact_count=3) == (
        "j",
        "k",
        "n",
        "p",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=0, artifact_count=3) == (
        "n",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=1, artifact_count=3) == (
        "n",
        "p",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=2, artifact_count=3) == (
        "p",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, return_pane_available=True) == (
        "\t",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, tmux_zoom_available=True) == (
        "r",
        "z",
        "q",
    )
    assert page_loop_available_keys(
        0,
        1,
        return_pane_available=True,
        tmux_zoom_available=True,
    ) == (
        "\t",
        "r",
        "z",
        "q",
    )
    assert page_loop_available_keys(
        1,
        3,
        artifact_index=1,
        artifact_count=3,
        return_pane_available=True,
    ) == (
        "\t",
        "j",
        "k",
        "n",
        "p",
        "r",
        "q",
    )
    assert "h" not in page_loop_available_keys(
        0,
        1,
        return_pane_available=True,
    )
    assert "z" not in page_loop_available_keys(
        0,
        1,
        return_pane_available=True,
    )

    _print_page_prompt(index=0, page_count=1)
    output = capsys.readouterr().out
    assert _strip_ansi(output) == "\nPage 1/1  r: refresh  q: quit"
    assert _viewer_loop._FOOTER_COLOR in output
    assert output.startswith(_viewer_loop._FOOTER_RESET)
    assert output.endswith(_viewer_loop._FOOTER_RESET)

    _print_page_prompt(index=0, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 1/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=1, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 2/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=2, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 3/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=0,
        page_count=1,
        artifact_index=0,
        artifact_count=2,
    )
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nArtifact 1/2  Page 1/1  n: next artifact  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=0,
        page_count=1,
        artifact_index=0,
        artifact_count=2,
        show_position=False,
    )
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nn: next artifact  r: refresh  q: quit"
    )

    _print_page_prompt(index=0, page_count=1, return_pane_available=True)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 1/1  <tab>: focus SASE TUI  r: refresh  q: quit"
    )

    _print_page_prompt(index=0, page_count=1, tmux_zoom_available=True)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 1/1  r: refresh  z: zoom  q: quit"
    )

    _print_page_prompt(
        index=1,
        page_count=3,
        artifact_index=1,
        artifact_count=3,
        return_pane_available=True,
    )
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nArtifact 2/3  Page 2/3  <tab>: focus SASE TUI  j: next page  "
        "k: previous page  n: next artifact  p: previous artifact  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=1,
        page_count=3,
        artifact_index=1,
        artifact_count=3,
        show_position=False,
        return_pane_available=True,
    )
    assert _strip_ansi(capsys.readouterr().out) == (
        "\n<tab>: focus SASE TUI  j: next page  k: previous page  n: next artifact  "
        "p: previous artifact  r: refresh  q: quit"
    )
