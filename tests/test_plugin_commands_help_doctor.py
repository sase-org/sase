"""Tests for plugin commands in root help and ``sase doctor`` (help-doctor phase).

Uses the shared fake-distribution harness from ``tests/_plugin_commands_fake``.
Root-help tests stay hermetic through the session autouse
``SASE_DISABLE_PLUGIN_COMMANDS`` guard unless the ``fake_plugin_commands``
fixture unsets it for the test.
"""

from __future__ import annotations

import pytest

from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.text import Text

from sase.main.parser import create_parser
from sase.main.parser_root_help import (
    format_colored_compact_root_help,
    format_colored_plugin_commands_footer,
    format_compact_root_help,
    format_plugin_commands_footer,
)
from tests._plugin_commands_fake import FakeCommandSpec
from tests.main.parser_help_helpers import (
    ANSI_RE,
    TtyStringIO,
    help_subcommand_rows,
    parse_and_capture_help,
    root_subparser_action,
    strip_ansi,
)


def _render_text(text: Text) -> str:
    """Render Rich text through a forced terminal for ANSI assertions."""
    stream = StringIO()
    console = Console(file=stream, force_terminal=True, highlight=False)
    console.print(text, end="", soft_wrap=True)
    return stream.getvalue()


def test_compact_help_lists_plugin_command_group(fake_plugin_commands) -> None:
    """Compact ``sase -h`` shows mounted commands with provenance."""
    fake_plugin_commands(
        commands={"listen": FakeCommandSpec(summary="Turn Markdown into MP3")}
    )
    help_text = format_compact_root_help(create_parser())

    assert "Plugin commands:" in help_text
    common_index = help_text.index("Common commands:")
    plugin_index = help_text.index("Plugin commands:")
    examples_index = help_text.index("Examples:")
    assert common_index < plugin_index < examples_index
    assert "listen" in help_text
    assert "Turn Markdown into MP3" in help_text
    assert "· fake-listen" in help_text


def test_compact_help_omits_plugin_group_without_commands() -> None:
    """Compact help is unchanged when no plugin command is mounted."""
    help_text = format_compact_root_help(create_parser())

    assert "Plugin commands:" not in help_text


def test_compact_help_hides_problem_states(fake_plugin_commands) -> None:
    """Shadowed and conflicting claims stay out of compact ``sase -h``."""
    fake_plugin_commands(commands={"run": FakeCommandSpec()})
    help_text = format_compact_root_help(create_parser())

    assert "Plugin commands:" not in help_text


def test_compact_help_colored_group_strips_to_plain(fake_plugin_commands) -> None:
    """Colored compact help carries the group without changing plain text."""
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    parser = create_parser()

    colored = format_colored_compact_root_help(parser)

    rendered = strip_ansi(_render_text(colored))
    assert rendered == format_compact_root_help(parser)


def test_full_help_footer_lists_chip_summary_and_provenance(
    fake_plugin_commands,
) -> None:
    """``sase -H`` footer shows the chip, summary, and distribution version."""
    fake_plugin_commands(
        commands={"listen": FakeCommandSpec(summary="Turn Markdown into MP3")}
    )
    footer = format_plugin_commands_footer()

    assert "Plugin commands:" in footer
    assert "❯ sase listen" in footer
    assert "Turn Markdown into MP3" in footer
    assert "(fake-listen 0.1.2)" in footer
    assert (
        "Manage plugins with sase plugin list or the Updates tab in sase's Admin Center."
        in footer
    )


def test_full_help_footer_empty_without_commands() -> None:
    """No plugin commands means no footer at all."""
    assert format_plugin_commands_footer() == ""
    assert format_colored_plugin_commands_footer() is None


def test_full_help_footer_reports_problem_rows(fake_plugin_commands) -> None:
    """Shadowed, conflict, invalid, and load-failure rows render with ⚠."""
    fake_plugin_commands(
        dist_name="fake-one",
        commands={
            "run": FakeCommandSpec(),
            "Bad_Name": FakeCommandSpec(),
            "broken": FakeCommandSpec(broken_import=True),
        },
    )
    fake_plugin_commands(
        dist_name="fake-two",
        commands={"dupe": FakeCommandSpec(), "broken-too": FakeCommandSpec()},
    )
    fake_plugin_commands(
        dist_name="fake-three",
        commands={"dupe": FakeCommandSpec()},
    )
    footer = format_plugin_commands_footer()

    assert "⚠ sase run" in footer
    assert "⚠ sase Bad_Name" in footer
    assert "⚠ sase broken" in footer
    assert "⚠ sase dupe" in footer
    assert "fake-two" in footer
    assert "fake-three" in footer
    assert "sase doctor" in footer


def test_full_help_output_keeps_every_argparse_choice(
    fake_plugin_commands, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-H`` output still contains the full argparse command inventory."""
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    parser = create_parser()
    expected_commands = set(root_subparser_action(parser).choices)

    help_text = parse_and_capture_help(["--full-help"], capsys)
    help_commands = set(help_subcommand_rows(help_text, expected_commands))

    assert expected_commands <= help_commands
    assert "❯ sase listen" in help_text


def test_full_help_footer_colored_strips_to_plain(fake_plugin_commands) -> None:
    """Colored footer renders ANSI without changing the stripped text."""
    fake_plugin_commands(
        commands={
            "listen": FakeCommandSpec(),
            "broken": FakeCommandSpec(broken_import=True),
        },
    )
    footer = format_colored_plugin_commands_footer()

    assert footer is not None
    assert ANSI_RE.search(_render_text(footer)) is not None
    assert strip_ansi(_render_text(footer)) == format_plugin_commands_footer()


def test_full_help_tty_footer_stays_plain_without_color_support(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The footer path honors NO_COLOR like the rest of root help."""
    from sase.main.parser_root_help import print_plugin_commands_footer

    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    monkeypatch.setenv("NO_COLOR", "1")
    stream = StringIO()

    print_plugin_commands_footer(stream)

    assert ANSI_RE.search(stream.getvalue()) is None
    assert "❯ sase listen" in stream.getvalue()


# --- plugins.commands doctor check ---


def test_doctor_plugin_commands_ok_lists_mounted(fake_plugin_commands) -> None:
    """OK names each mounted command with its owning distribution."""
    from sase.doctor.checks_plugins import _check_plugin_commands

    fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    check = _check_plugin_commands()

    assert check.id == "plugins.commands"
    assert check.status == "OK"
    assert "❯ sase listen" in check.summary or "listen" in check.summary
    assert any("fake-listen" in detail for detail in check.details)
    assert check.data["mounted_count"] == 1


def test_doctor_plugin_commands_warns_on_shadowed_and_invalid(
    fake_plugin_commands,
) -> None:
    """Shadowed and invalid names are WARN and name their distributions."""
    from sase.doctor.checks_plugins import _check_plugin_commands

    fake_plugin_commands(
        dist_name="fake-shadow",
        commands={"run": FakeCommandSpec(), "Bad_Name": FakeCommandSpec()},
    )

    check = _check_plugin_commands()

    assert check.status == "WARN"
    assert any("fake-shadow" in detail for detail in check.details)
    assert check.next_steps
    assert all("sase plugin uninstall" in step for step in check.next_steps)


def test_doctor_plugin_commands_errors_on_conflict(fake_plugin_commands) -> None:
    """Duplicate owners are ERROR and name every owner."""
    from sase.doctor.checks_plugins import _check_plugin_commands

    fake_plugin_commands(dist_name="fake-a", commands={"dupe": FakeCommandSpec()})
    fake_plugin_commands(dist_name="fake-b", commands={"dupe": FakeCommandSpec()})

    check = _check_plugin_commands()

    assert check.status == "ERROR"
    assert any("fake-a" in detail and "fake-b" in detail for detail in check.details)
    assert any("sase plugin uninstall" in step for step in check.next_steps)


def test_doctor_plugin_commands_errors_on_load_failure(
    fake_plugin_commands,
) -> None:
    """Broken adapters, API mismatches, and missing members are ERROR."""
    from sase.doctor.checks_plugins import _check_plugin_commands

    fake_plugin_commands(
        commands={
            "broken": FakeCommandSpec(broken_import=True),
            "future": FakeCommandSpec(api_version=99),
            "nomain": FakeCommandSpec(omit=("main",)),
        }
    )

    check = _check_plugin_commands()

    assert check.status == "ERROR"
    assert check.data["error_count"] == 3
    assert any("sase plugin update broken" in step for step in check.next_steps)
    assert any("fake-listen" in detail for detail in check.details)


def test_doctor_plugin_commands_deep_builds_parsers(fake_plugin_commands) -> None:
    """The deep variant catches parser-construction failures."""
    from sase.doctor.checks_plugins import (
        _check_plugin_command_parsers,
        _check_plugin_commands,
    )

    fake_plugin_commands(
        commands={
            "good": FakeCommandSpec(),
            "badparser": FakeCommandSpec(
                omit=("build_parser",),
                extra_source=(
                    "def build_parser(prog='sase CMD'):\n"
                    "    raise RuntimeError('cannot build parser')\n"
                ),
            ),
        }
    )

    shallow = _check_plugin_commands()
    deep = _check_plugin_command_parsers()

    assert shallow.status == "OK"
    assert deep.id == "plugins.commands-parsers"
    assert deep.status == "ERROR"
    assert any("badparser" in detail for detail in deep.details)
    assert any("sase plugin update badparser" in step for step in deep.next_steps)


def test_doctor_plugin_command_specs_registered(tmp_path: Path) -> None:
    """Both specs are registered with the deep flag only on the parsers one."""
    from sase.doctor.runner import DoctorContext, build_doctor_registry

    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)
    registry = build_doctor_registry(context)
    specs = {spec.id: spec for spec in registry.list_checks(include_deep=True)}

    assert specs["plugins.commands"].deep is False
    assert specs["plugins.commands-parsers"].deep is True
    assert specs["plugins.commands-parsers"].group == "plugins"


def test_compact_help_tty_output_matches_plain(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: TTY ``-h`` output strips to the plain rendering."""
    from sase.main.parser import _print_compact_root_help

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    parser = create_parser()
    output = TtyStringIO()

    _print_compact_root_help(parser, output)

    assert strip_ansi(output.getvalue()) == format_compact_root_help(parser)
