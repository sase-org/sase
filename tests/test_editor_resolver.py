from __future__ import annotations

from sase.editor_resolver import resolve_editor


def test_resolve_editor_prefers_visual_and_splits_args() -> None:
    resolution = resolve_editor(
        env={"VISUAL": "code --wait", "EDITOR": "vim"},
        which=lambda command: "/usr/bin/code" if command == "code" else None,
    )

    assert resolution.status == "resolved"
    assert resolution.source == "VISUAL"
    assert resolution.argv == ("code", "--wait")
    assert resolution.command_string == "code --wait"
    assert resolution.argv_with_path("/tmp/prompt.md") == [
        "code",
        "--wait",
        "/tmp/prompt.md",
    ]


def test_resolve_editor_uses_editor_when_visual_empty() -> None:
    resolution = resolve_editor(
        env={"VISUAL": "", "EDITOR": "vim -f"},
        which=lambda command: "/usr/bin/vim" if command == "vim" else None,
    )

    assert resolution.status == "resolved"
    assert resolution.source == "EDITOR"
    assert resolution.argv == ("vim", "-f")


def test_resolve_editor_warns_on_missing_configured_head() -> None:
    resolution = resolve_editor(
        env={"EDITOR": "missing-editor --wait"},
        which=lambda _command: None,
    )

    assert resolution.status == "missing"
    assert resolution.source == "EDITOR"
    assert resolution.head == "missing-editor"


def test_resolve_editor_warns_on_shell_style_config() -> None:
    resolution = resolve_editor(
        env={"EDITOR": "$HOME/bin/editor --wait"},
        which=lambda _command: None,
    )

    assert resolution.status == "unverified_shell"
    assert resolution.argv == ("$HOME/bin/editor", "--wait")


def test_resolve_editor_falls_back_to_nvim_then_vim() -> None:
    resolution = resolve_editor(
        env={},
        which=lambda command: f"/usr/bin/{command}" if command == "vim" else None,
    )

    assert resolution.status == "resolved"
    assert resolution.source == "fallback"
    assert resolution.argv == ("vim",)


def test_resolve_editor_warns_when_no_fallback_resolves() -> None:
    resolution = resolve_editor(env={}, which=lambda _command: None)

    assert resolution.status == "missing"
    assert resolution.source == "fallback"
    assert resolution.argv == ("vim",)
