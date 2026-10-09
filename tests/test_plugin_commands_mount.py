"""Mount-phase coverage for plugin-mounted top-level commands.

Uses the shared fake-distribution harness
(:mod:`tests._plugin_commands_fake`); the hermetic
``SASE_DISABLE_PLUGIN_COMMANDS`` guard from ``tests/conftest.py`` stays on
unless the ``fake_plugin_commands`` fixture unsets it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sase.legacy_xprompt_syntax import RETIRED_ROOT_COMMAND
from sase.plugin_commands import chip as chip_module
from sase.plugin_commands.adapter import (
    PluginCommandLoadError,
    load_plugin_command,
    resolve_command_summary,
)
from sase.plugin_commands.dispatch import try_handle_plugin_command
from sase.plugin_commands.registry import (
    discover_plugin_commands,
    _reserved_command_names,
    _validate_command_name,
)
from sase.plugin_commands.scan import (
    commands_disabled,
    scan_plugin_commands,
)
from tests._plugin_commands_fake import (
    FakeCommandSpec,
    install_fake_distribution,
    read_call_log,
    subprocess_env,
)


def test_dispatch_runs_mounted_command_with_untouched_argv(
    fake_plugin_commands,
) -> None:
    dist = fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    assert try_handle_plugin_command(["listen", "--mode", "fast"]) == 0

    calls = read_call_log(dist.site_dir)
    assert len(calls) == 1
    assert calls[0]["argv"] == ["--mode", "fast"]
    assert calls[0]["prog"] == "sase listen"
    assert calls[0]["sys_argv"] == ["sase listen", "--mode", "fast"]


def test_dispatch_none_exit_code_means_zero(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec(exit_code=None)})

    assert try_handle_plugin_command(["listen"]) == 0


def test_dispatch_entry_point_sets_sys_argv_and_exit_code(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main import entry

    fake_plugin_commands(commands={"listen": FakeCommandSpec(exit_code=3)})

    monkeypatch.setattr(sys, "argv", ["sase", "listen", "--mode", "slow"])
    with pytest.raises(SystemExit) as actual_exit:
        entry.main()

    assert actual_exit.value.code == 3


def test_dispatch_global_options_consumed_before_command_word(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main import entry

    dist = fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    monkeypatch.setattr(sys, "argv", ["sase", "-p", "listen", "--mode", "fast"])
    with pytest.raises(SystemExit) as actual_exit:
        entry.main()

    assert actual_exit.value.code == 0
    calls = read_call_log(dist.site_dir)
    assert [call["argv"] for call in calls] == [["--mode", "fast"]]


def test_dispatch_passes_help_and_double_dash_through(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    assert try_handle_plugin_command(["listen", "-h"]) == 0
    assert try_handle_plugin_command(["listen", "--", "--help"]) == 0


def test_dispatch_system_exit_propagates_unchanged(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec(raise_system_exit=3)})

    with pytest.raises(SystemExit) as actual_exit:
        try_handle_plugin_command(["listen"])

    assert actual_exit.value.code == 3


def test_dispatch_module_object_value(fake_plugin_commands) -> None:
    dist = fake_plugin_commands(
        commands={"listen": FakeCommandSpec(object_target="adapter")}
    )

    assert try_handle_plugin_command(["listen"]) == 0
    assert len(read_call_log(dist.site_dir)) == 1


def test_reserved_names_cover_builtins_legacy_aliases_and_help() -> None:
    reserved = _reserved_command_names()

    assert {"doctor", "bead", "plugin", "completion"} <= reserved
    # Legacy aliases share registrars and stay reserved.
    assert {"task", "changespec", "vcs"} <= reserved
    assert "help" in reserved
    assert RETIRED_ROOT_COMMAND in reserved
    assert "listen" not in reserved


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("listen", True),
        ("a", True),
        ("x-1-2", True),
        ("a" + "b" * 31, True),
        ("a" + "b" * 32, False),
        ("Listen", False),
        ("bad_name", False),
        ("-bad", False),
        ("", False),
    ],
)
def test_validate_command_name(name: str, valid: bool) -> None:
    assert _validate_command_name(name) == valid


def test_shadowed_builtin_and_legacy_names_fall_through(fake_plugin_commands) -> None:
    fake_plugin_commands(
        dist_name="fake-shadow",
        commands={
            "doctor": FakeCommandSpec(),
            "task": FakeCommandSpec(),
            "help": FakeCommandSpec(),
        },
    )

    command_set = discover_plugin_commands()
    assert {problem.name for problem in command_set.problems} == {
        "doctor",
        "help",
        "task",
    }
    assert all(problem.status == "shadowed" for problem in command_set.problems)
    assert command_set.mounted == ()

    assert try_handle_plugin_command(["doctor"]) is None
    assert try_handle_plugin_command(["help"]) is None


def test_duplicate_owners_disable_with_named_conflict(
    fake_plugin_commands, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_plugin_commands(dist_name="fake-one", commands={"dup": FakeCommandSpec()})
    fake_plugin_commands(dist_name="fake-two", commands={"dup": FakeCommandSpec()})

    command_set = discover_plugin_commands()
    assert [problem.status for problem in command_set.problems] == ["conflict"]
    assert command_set.problems[0].distributions == ("fake-one", "fake-two")
    assert command_set.mounted == ()

    assert try_handle_plugin_command(["dup"]) == 1
    _, err = capsys.readouterr()
    assert "fake-one" in err and "fake-two" in err
    assert "sase plugin uninstall" in err


def test_invalid_names_never_mount(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"Bad_Name": FakeCommandSpec()})

    command_set = discover_plugin_commands()
    assert [problem.status for problem in command_set.problems] == ["invalid_name"]
    assert command_set.mounted == ()
    assert try_handle_plugin_command(["Bad_Name"]) is None


def test_disable_switches_turn_off_dispatch(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    assert discover_plugin_commands().mounted != ()

    monkeypatch.setenv("SASE_DISABLE_PLUGIN_COMMANDS", "1")
    assert commands_disabled()
    assert scan_plugin_commands() == ()
    assert discover_plugin_commands().mounted == ()


def test_global_disable_switch_turns_off_dispatch(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    monkeypatch.delenv("SASE_DISABLE_PLUGIN_COMMANDS", raising=False)
    monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    assert commands_disabled()
    assert discover_plugin_commands().mounted == ()


def test_disabled_command_names_disabling_switch(
    fake_plugin_commands,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})

    monkeypatch.setenv("SASE_DISABLE_PLUGIN_COMMANDS", "1")
    assert try_handle_plugin_command(["listen"]) == 2
    _, err = capsys.readouterr()
    assert "SASE_DISABLE_PLUGIN_COMMANDS" in err


def test_api_mismatch_missing_members_and_import_failure(
    fake_plugin_commands, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_plugin_commands(
        dist_name="fake-future",
        commands={"future": FakeCommandSpec(api_version=99)},
    )
    fake_plugin_commands(
        dist_name="fake-partial",
        commands={"partial": FakeCommandSpec(omit=("main",))},
    )
    fake_plugin_commands(
        dist_name="fake-broken",
        commands={"broken": FakeCommandSpec(broken_import=True)},
    )

    assert try_handle_plugin_command(["future"]) == 1
    assert "requires a newer sase" in capsys.readouterr().err

    assert try_handle_plugin_command(["partial"]) == 1
    assert "'main'" in capsys.readouterr().err

    assert try_handle_plugin_command(["broken"]) == 1
    err = capsys.readouterr().err
    assert "failed to load" in err
    assert "sase plugin update broken" in err


def test_load_failure_names_distribution_and_repair(
    fake_plugin_commands, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_plugin_commands(
        dist_name="fake-listen",
        version="0.1.2",
        commands={"listen": FakeCommandSpec(broken_import=True)},
    )

    assert try_handle_plugin_command(["listen"]) == 1
    _, err = capsys.readouterr()
    assert "the 'listen' command from fake-listen 0.1.2 failed to load" in err
    assert "sase plugin update listen" in err


def test_summary_prefers_adapter_summary_over_dist_metadata(
    fake_plugin_commands,
) -> None:
    dist = fake_plugin_commands(
        commands={"listen": FakeCommandSpec(summary="Adapter summary")},
        metadata_summary="Dist summary",
    )
    (record,) = scan_plugin_commands()
    loaded = load_plugin_command(record)
    assert loaded.summary == "Adapter summary"

    other = fake_plugin_commands(
        dist_name="fake-other",
        commands={"other": FakeCommandSpec(summary="x", extra_source="SUMMARY = ''")},
        metadata_summary="Dist summary here",
    )
    assert other.site_dir != dist.site_dir
    records = {record.name: record for record in scan_plugin_commands()}
    assert resolve_command_summary(records["other"]) == "Dist summary here"


def test_load_plugin_command_error_carries_owner(fake_plugin_commands) -> None:
    fake_plugin_commands(
        dist_name="fake-future",
        version="2.0.0",
        commands={"future": FakeCommandSpec(api_version=99)},
    )

    (record,) = scan_plugin_commands()
    with pytest.raises(PluginCommandLoadError) as error:
        load_plugin_command(record)

    assert error.value.command == "future"
    assert error.value.distribution == "fake-future"
    assert error.value.version == "2.0.0"
    assert "sase update" in error.value.cause


def test_scan_records_sort_and_editable(fake_plugin_commands, tmp_path: Path) -> None:
    editable_dist = fake_plugin_commands(
        dist_name="fake-edit",
        commands={"zeta": FakeCommandSpec(), "alpha": FakeCommandSpec()},
        editable=True,
    )

    records = scan_plugin_commands()
    assert [record.name for record in records] == ["alpha", "zeta"]
    assert all(record.editable for record in records)
    assert all(str(tmp_path) in record.location for record in records)
    assert editable_dist.dist_info_dir.exists()


def test_scan_hermetic_guard_hides_developer_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_distribution(
        tmp_path,
        monkeypatch,
        commands={"listen": FakeCommandSpec()},
        track_modules=[],
    )

    assert commands_disabled()
    assert scan_plugin_commands() == ()
    assert len(scan_plugin_commands(honor_disable=False)) == 1


def test_hint_for_installed_distribution_predating_command(
    fake_plugin_commands, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_plugin_commands(dist_name="sase-oldy", version="0.1.1", commands=None)

    assert try_handle_plugin_command(["oldy"]) == 2
    _, err = capsys.readouterr()
    assert "sase-oldy 0.1.1 is installed but predates 'sase oldy'" in err
    assert "sase plugin update oldy" in err


def test_hint_for_catalogued_not_installed_plugin(
    fake_plugin_commands,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.plugins.cache import write_cache

    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    write_cache(
        [
            {
                "name": "listen",
                "repo": "sase-listen",
                "full_name": "sase-org/sase-listen",
                "owner": "sase-org",
                "description": "audio",
                "url": "https://github.com/sase-org/sase-listen",
                "homepage": "",
                "topics": ["sase--plugin"],
                "stars": 1,
                "archived": False,
                "license": "MIT",
                "updated_at": "",
            }
        ],
        fetched_at=1_700_000_000.0,
        query="topic:sase--plugin",
    )

    assert try_handle_plugin_command(["listen"]) == 2
    _, err = capsys.readouterr()
    assert "'listen' is provided by the listen plugin (sase-org/sase-listen)" in err
    assert "sase plugin install listen" in err


def test_unknown_word_without_hint_falls_through(fake_plugin_commands) -> None:
    assert try_handle_plugin_command(["bogus"]) is None
    assert try_handle_plugin_command([]) is None
    assert try_handle_plugin_command(["--help"]) is None


def test_command_chip_plain_and_rich() -> None:
    assert chip_module.format_command_chip("listen") == "❯ sase listen"


def test_scan_module_stays_free_of_parser_imports(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import sys
        import sase.plugin_commands.scan as scan

        scan.scan_plugin_commands(honor_disable=False)
        forbidden = sorted(
            name
            for name in sys.modules
            if name == "sase.main.parser"
            or name == "sase.main.parser_registry"
            or name == "sase.completion.build"
            or name.startswith("sase.ace")
            or name == "textual"
            or name.startswith("textual.")
            or name == "rich"
            or name.startswith("rich.")
        )
        assert not forbidden, forbidden
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=subprocess_env(tmp_path, enable_commands=False),
    )
    assert result.returncode == 0, result.stderr


def test_builtin_dispatch_avoids_metadata_import(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import sys
        from sase.plugin_commands.dispatch import try_handle_plugin_command

        assert try_handle_plugin_command(["doctor"]) is None
        assert try_handle_plugin_command(["--help"]) is None
        assert "importlib.metadata" not in sys.modules
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=subprocess_env(tmp_path, enable_commands=False),
    )
    assert result.returncode == 0, result.stderr
