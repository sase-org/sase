"""Tests for shell detection and completion target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.completion.install_targets import (
    CannotDetectShell,
    CompletionInstallError,
    _conventional_dir,
    _normalize_shell_name,
    _script_filename,
    detect_shell,
    fpath_hint_line,
    resolve_target,
    script_path,
)


def test_normalize_shell_name_maps_paths_and_login_comms() -> None:
    assert _normalize_shell_name("/usr/bin/zsh") == "zsh"
    assert _normalize_shell_name("-zsh") == "zsh"
    assert _normalize_shell_name("/bin/bash") == "bash"
    assert _normalize_shell_name("fish") == "fish"
    assert _normalize_shell_name("python") is None


def test_detect_shell_prefers_explicit_then_parent_then_env() -> None:
    explicit = detect_shell(
        requested="zsh",
        environ={"SHELL": "/bin/bash"},
        parent="fish",
    )
    assert explicit.name == "zsh"
    assert explicit.source == "explicit"

    parent = detect_shell(environ={"SHELL": "/bin/bash"}, parent="zsh")
    assert parent.name == "zsh"
    assert "parent process" in parent.source

    env = detect_shell(environ={"SHELL": "/usr/bin/fish"}, parent="python")
    assert env.name == "fish"
    assert env.source == "$SHELL=/usr/bin/fish"


def test_detect_shell_reports_failure_instead_of_guessing() -> None:
    with pytest.raises(CannotDetectShell, match="pass bash, fish, or zsh"):
        detect_shell(environ={}, parent=None)


def test_detect_shell_rejects_unsupported_explicit_shell() -> None:
    with pytest.raises(CompletionInstallError, match="unsupported shell"):
        detect_shell(requested="powershell", parent=None)


def test_resolve_target_honors_priority_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    conventional = _conventional_dir("zsh", home=home, environ={})
    env_dir = tmp_path / "from-env"
    target = tmp_path / "from-flag"

    chosen = resolve_target(
        "zsh",
        target=target,
        environ={"SASE_COMPLETION_DIR": str(env_dir)},
        home=home,
        scanned=(scanned,),
    )
    assert chosen.directory == target
    assert chosen.reason == "--target"

    chosen = resolve_target(
        "zsh",
        environ={"SASE_COMPLETION_DIR": str(env_dir)},
        home=home,
        scanned=(scanned,),
    )
    assert chosen.directory == env_dir
    assert chosen.reason == "SASE_COMPLETION_DIR"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(scanned,),
        writable=lambda path: path == scanned,
    )
    assert chosen.directory == scanned
    assert chosen.reason == "scanned directory"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(scanned,),
        writable=lambda _path: False,
    )
    assert chosen.directory == conventional
    assert chosen.reason == "conventional directory"


def test_unwritable_scanned_dir_falls_through_to_conventional(tmp_path: Path) -> None:
    home = tmp_path / "home"
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    conventional = _conventional_dir("bash", home=home, environ={})

    chosen = resolve_target(
        "bash",
        environ={},
        home=home,
        scanned=(blocked,),
        writable=lambda path: path != blocked,
    )
    assert chosen.directory == conventional
    assert chosen.reason == "conventional directory"


def test_framework_plugin_dirs_lose_to_the_drop_in_dir(tmp_path: Path) -> None:
    # oh-my-zsh puts every enabled plugin's own directory on fpath first, and
    # they are all writable: installing there hijacks an unrelated project's
    # tree and unloads sase completion the day that plugin is disabled. Its
    # $ZSH_CUSTOM drop-in directory is the sanctioned target.
    home = tmp_path / "home"
    plugin = home / ".oh-my-zsh" / "plugins" / "z"
    cached = home / ".cache" / "oh-my-zsh" / "completions"
    drop_in = home / ".oh-my-zsh" / "completions"
    custom_drop_in = home / ".oh-my-zsh" / "custom" / "completions"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(plugin, cached, drop_in, custom_drop_in),
        writable=lambda _path: True,
    )
    assert chosen.directory == custom_drop_in
    assert chosen.reason == "framework completions directory"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(plugin, cached, drop_in),
        writable=lambda _path: True,
    )
    assert chosen.directory == drop_in


def test_a_creatable_drop_in_beats_a_plain_scanned_dir(tmp_path: Path) -> None:
    # The fpath probe reads fpath after rc processing, so it cannot tell a
    # directory scanned before compinit from one appended after it, where a
    # script is a silent no-op. The framework's own drop-in entry is the one
    # with guaranteed ordering, so it wins even when it has to be created.
    home = tmp_path / "home"
    zfunc = home / ".zfunc"
    zfunc.mkdir(parents=True)
    drop_in = home / ".oh-my-zsh" / "custom" / "completions"
    drop_in.parent.mkdir(parents=True)

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(zfunc, drop_in),
    )
    assert chosen.directory == drop_in
    assert chosen.reason == "framework completions directory"


def test_a_drop_in_whose_parent_is_unwritable_is_skipped(tmp_path: Path) -> None:
    home = tmp_path / "home"
    zfunc = home / ".zfunc"
    drop_in = home / ".oh-my-zsh" / "custom" / "completions"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(zfunc, drop_in),
        writable=lambda path: path == zfunc,
    )
    assert chosen.directory == zfunc
    assert chosen.reason == "scanned directory"


def test_framework_only_fpath_falls_through_to_conventional(tmp_path: Path) -> None:
    home = tmp_path / "home"
    conventional = _conventional_dir("zsh", home=home, environ={})

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(
            home / ".oh-my-zsh" / "custom" / "plugins" / "zsh-autosuggestions",
            home / ".zprezto" / "modules" / "completion" / "external" / "src",
            home / ".local" / "share" / "zinit" / "plugins" / "some---plugin",
        ),
        writable=lambda _path: True,
    )
    assert chosen.directory == conventional
    assert chosen.reason == "conventional directory"


def test_xdg_cache_scanned_dirs_are_skipped(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache_root = tmp_path / "xdg-cache"
    conventional = _conventional_dir("zsh", home=home, environ={})

    chosen = resolve_target(
        "zsh",
        environ={"XDG_CACHE_HOME": str(cache_root)},
        home=home,
        scanned=(cache_root / "zsh" / "completions",),
        writable=lambda _path: True,
    )
    assert chosen.directory == conventional
    assert chosen.reason == "conventional directory"


def test_home_scanned_dir_wins_over_a_writable_system_one(tmp_path: Path) -> None:
    home = tmp_path / "home"
    system = tmp_path / "usr" / "local" / "share" / "zsh" / "site-functions"
    zfunc = home / ".zfunc"

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(system, zfunc),
        writable=lambda _path: True,
    )
    assert chosen.directory == zfunc

    chosen = resolve_target(
        "zsh",
        environ={},
        home=home,
        scanned=(system,),
        writable=lambda _path: True,
    )
    assert chosen.directory == system
    assert chosen.reason == "scanned directory"


def test_script_names_and_fpath_hint(tmp_path: Path) -> None:
    assert _script_filename("zsh") == "_sase"
    assert _script_filename("bash") == "sase"
    assert _script_filename("fish") == "sase.fish"
    assert script_path(tmp_path, "zsh") == tmp_path / "_sase"
    home = tmp_path / "home"
    zfunc = home / ".zfunc"
    zfunc.mkdir(parents=True)
    assert fpath_hint_line(zfunc, home=home) == (
        "fpath=(~/.zfunc $fpath)   # must appear BEFORE compinit"
    )
