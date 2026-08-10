"""Tests for the ``sase stitch`` parser and handler dispatch."""

from __future__ import annotations

import argparse
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from tests.main.parser_cli_helpers import parse_sase_args


class TestStitchParser:
    def test_bare_stitch_defaults_to_list(self) -> None:
        ns = parse_sase_args(["stitch"])

        assert ns.command == "stitch"
        assert ns.stitch_subcommand == "list"
        assert ns.repos == []
        assert ns.current_only is False
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.no_fetch is False
        assert ns.sort == "default"

    def test_list_defaults(self) -> None:
        ns = parse_sase_args(["stitch", "list"])

        assert ns.stitch_subcommand == "list"
        assert ns.repos == []
        assert ns.current_only is False
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.no_fetch is False
        assert ns.sort == "default"

    def test_list_options(self) -> None:
        ns = parse_sase_args(
            [
                "stitch",
                "list",
                "-c",
                "never",
                "-f",
                "json",
                "-N",
                "-o",
                "-r",
                "sase-core",
                "-s",
                "recent",
            ]
        )

        assert ns.color == "never"
        assert ns.format == "json"
        assert ns.no_fetch is True
        assert ns.current_only is True
        assert ns.repos == ["sase-core"]
        assert ns.sort == "recent"

    def test_legacy_vcs_alias_defaults_to_list(self) -> None:
        canonical = parse_sase_args(["stitch"])
        legacy = parse_sase_args(["vcs"])

        assert legacy.command == "vcs"
        assert legacy.stitch_subcommand == "list"
        for key in (
            "stitch_subcommand",
            "repos",
            "current_only",
            "format",
            "color",
            "no_fetch",
            "sort",
        ):
            assert getattr(legacy, key) == getattr(canonical, key)

    def test_log_defaults(self) -> None:
        ns = parse_sase_args(["stitch", "log"])

        assert ns.stitch_subcommand == "log"
        assert ns.all is False
        assert ns.limit == 40
        assert ns.authors == []
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.merges == "hide"
        assert ns.no_fetch is False
        assert ns.force_fetch is False
        assert ns.remote_ref is None
        assert ns.reverse is False
        assert ns.sdd is False
        assert ns.since is None
        assert ns.show_tags is True
        assert ns.until is None

    def test_log_limit_and_format_and_color(self) -> None:
        ns = parse_sase_args(
            ["stitch", "log", "-n", "5", "--format", "full", "--color", "never"]
        )

        assert ns.limit == 5
        assert ns.format == "full"
        assert ns.color == "never"

    @pytest.mark.parametrize("mode", ["hide", "show", "only"])
    def test_log_merges_option(self, mode: str) -> None:
        ns = parse_sase_args(["stitch", "log", "--merges", mode])

        assert ns.merges == mode

    def test_log_merges_short_option(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-m", "show"])

        assert ns.merges == "show"

    def test_log_rejects_unknown_merges_mode(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["stitch", "log", "--merges", "both"])

    def test_log_short_format_and_color_aliases(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-f", "json", "-c", "never"])

        assert ns.format == "json"
        assert ns.color == "never"

    def test_log_remote_options(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-b", "main", "-N"])

        assert ns.remote_ref == "main"
        assert ns.no_fetch is True

    def test_log_force_fetch_option(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-F"])

        assert ns.force_fetch is True
        assert ns.no_fetch is False

    def test_log_fetch_and_no_fetch_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_sase_args(["stitch", "log", "--fetch", "--no-fetch"])

        assert excinfo.value.code == 2

    def test_log_ref_alias(self) -> None:
        ns = parse_sase_args(["stitch", "log", "--ref", "release"])

        assert ns.remote_ref == "release"

    def test_log_repo_is_repeatable(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-r", "sase", "--repo", "sase-core"])

        assert ns.repos == ["sase", "sase-core"]

    def test_log_current_only_flag(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-o"])

        assert ns.current_only is True

    @pytest.mark.parametrize("option", ["-a", "--all"])
    def test_log_all_project_flags(self, option: str) -> None:
        ns = parse_sase_args(["stitch", "log", option])

        assert ns.all is True
        assert ns.authors == []

    def test_log_all_and_current_only_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_sase_args(["stitch", "log", "--all", "--current-only"])

        assert excinfo.value.code == 2

    def test_log_accepts_limit_zero(self) -> None:
        ns = parse_sase_args(["stitch", "log", "--limit", "0"])

        assert ns.limit == 0

    def test_log_rejects_negative_limit(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["stitch", "log", "-n", "-1"])

    def test_log_rejects_unknown_format(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["stitch", "log", "--format", "fancy"])

    def test_log_date_aliases_author_and_reverse(self) -> None:
        ns = parse_sase_args(
            [
                "stitch",
                "log",
                "--after",
                "2w",
                "--before",
                "today",
                "--author",
                "Bryan",
                "-A",
                "amy",
                "-R",
            ]
        )

        assert ns.since == "2w"
        assert ns.until == "today"
        assert ns.authors == ["Bryan", "amy"]
        assert ns.reverse is True

    def test_legacy_vcs_alias_resolves_log_defaults(self) -> None:
        canonical = parse_sase_args(["stitch", "log"])
        legacy = parse_sase_args(["vcs", "log"])

        assert legacy.command == "vcs"
        for key in (
            "stitch_subcommand",
            "all",
            "limit",
            "authors",
            "format",
            "color",
            "merges",
            "no_fetch",
            "force_fetch",
            "remote_ref",
            "reverse",
            "sdd",
            "since",
            "show_tags",
            "until",
        ):
            assert getattr(legacy, key) == getattr(canonical, key)

    def test_log_since_until_short_aliases(self) -> None:
        ns = parse_sase_args(["stitch", "log", "-s", "1d", "-u", "today"])

        assert ns.since == "1d"
        assert ns.until == "today"

    def test_log_no_tags_option(self) -> None:
        short = parse_sase_args(["stitch", "log", "-T"])
        long = parse_sase_args(["stitch", "log", "--no-tags"])

        assert short.show_tags is False
        assert long.show_tags is False

    @pytest.mark.parametrize("option", ["-S", "--sdd"])
    def test_log_sdd_flags(self, option: str) -> None:
        ns = parse_sase_args(["stitch", "log", option])

        assert ns.sdd is True

    def test_log_tags_aliases_remain_hidden_no_ops(self) -> None:
        short = parse_sase_args(["stitch", "log", "-t"])
        long = parse_sase_args(["stitch", "log", "--tags"])

        assert short.show_tags is True
        assert long.show_tags is True

    def test_log_help_shows_sorted_current_tag_and_fetch_options(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_sase_args(["stitch", "log", "-h"])

        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        assert "--fetch" in help_text
        assert "--no-fetch" in help_text
        assert "--no-tags" in help_text
        assert "-t, --tags" not in help_text
        options_text = help_text.split("options:\n", 1)[1]
        long_options = [
            "--all",
            "--author",
            "--branch",
            "--color",
            "--current-only",
            "--fetch",
            "--format",
            "--limit",
            "--merges",
            "--no-fetch",
            "--no-tags",
            "--repo",
            "--reverse",
            "--sdd",
            "--since",
            "--until",
        ]
        assert [options_text.index(option) for option in long_options] == sorted(
            options_text.index(option) for option in long_options
        )
        assert "Include commits from sidecar repositories" in " ".join(
            help_text.split()
        )
        assert (
            "Include repos from every registered enabled or disabled project"
            in " ".join(help_text.split())
        )


class TestStitchCreateParser:
    def test_create_defaults(self) -> None:
        ns = parse_sase_args(["stitch", "create"])

        assert ns.stitch_subcommand == "create"
        assert ns.message is None
        assert ns.message_file is None
        assert ns.files == []
        assert ns.name is None
        assert ns.bug_id == 0
        assert ns.do_not_close_bead is False
        assert ns.checkout_target == "HEAD~1"
        assert ns.parent is None
        assert ns.status is None
        assert ns.method is None
        assert ns.resume is False

    def test_create_message_flags_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_sase_args(["stitch", "create", "-m", "hi", "-M", "msg.txt"])

        assert excinfo.value.code == 2

    def test_create_file_is_repeatable(self) -> None:
        ns = parse_sase_args(["stitch", "create", "-f", "a.py", "--file", "b.py"])

        assert ns.files == ["a.py", "b.py"]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("create_commit", "create_commit"),
            ("create_proposal", "create_proposal"),
            ("create_pull_request", "create_pull_request"),
            ("commit", "commit"),
            ("propose", "propose"),
            ("pr", "pr"),
        ],
    )
    def test_create_type_accepts_canonical_methods_and_aliases(
        self, value: str, expected: str
    ) -> None:
        ns = parse_sase_args(["stitch", "create", "-t", value])

        assert ns.method == expected

    def test_create_rejects_unknown_type(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["stitch", "create", "-t", "bogus"])

    def test_create_resume_flag(self) -> None:
        ns = parse_sase_args(["stitch", "create", "-r"])

        assert ns.resume is True

    def test_create_short_flags_do_not_disturb_log_or_list_short_flags(self) -> None:
        create_ns = parse_sase_args(["stitch", "create", "-r", "-b", "7", "-c", "main"])
        log_ns = parse_sase_args(["stitch", "log", "-r", "sase-core", "-b", "main"])
        list_ns = parse_sase_args(["stitch", "list", "-c", "never"])

        assert create_ns.resume is True
        assert create_ns.bug_id == 7
        assert create_ns.checkout_target == "main"

        assert log_ns.repos == ["sase-core"]
        assert log_ns.remote_ref == "main"

        assert list_ns.color == "never"

    def test_bare_stitch_still_defaults_to_list_with_create_present(self) -> None:
        ns = parse_sase_args(["stitch"])

        assert ns.stitch_subcommand == "list"

    def test_unknown_subcommand_usage_string_names_create(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.stitch_handler import handle_stitch_command

        ns = argparse.Namespace(stitch_subcommand="bogus")
        with pytest.raises(SystemExit):
            handle_stitch_command(ns)

        assert "Usage: sase stitch {create,list,log}" in capsys.readouterr().err

    def test_commit_and_stitch_create_parse_to_equivalent_namespaces(self) -> None:
        argv = [
            "-M",
            "msg.txt",
            "-f",
            "a.py",
            "-f",
            "b.py",
            "-n",
            "feature",
            "-b",
            "7",
            "-B",
            "-c",
            "main",
            "-p",
            "parent_feature",
            "-s",
            "ready",
            "-t",
            "pr",
        ]

        commit_ns = parse_sase_args(["commit", *argv])
        create_ns = parse_sase_args(["stitch", "create", *argv])

        shared_keys = (
            "message",
            "message_file",
            "files",
            "name",
            "bug_id",
            "do_not_close_bead",
            "checkout_target",
            "parent",
            "status",
            "method",
            "resume",
        )
        for key in shared_keys:
            assert getattr(commit_ns, key) == getattr(create_ns, key), key


class TestStitchHandlerDispatch:
    def test_legacy_vcs_modules_export_legacy_names(self) -> None:
        from sase.main import parser_vcs, vcs_handler

        assert parser_vcs.register_vcs_parser is parser_vcs.register_stitch_parser
        assert vcs_handler.handle_vcs_command is vcs_handler.handle_stitch_command

    def test_unknown_subcommand_exits_2(self) -> None:
        from sase.main.stitch_handler import handle_stitch_command

        ns = argparse.Namespace(stitch_subcommand="bogus")
        with pytest.raises(SystemExit) as excinfo:
            handle_stitch_command(ns)
        assert excinfo.value.code == 2

    def test_missing_subcommand_exits_2(self) -> None:
        from sase.main.stitch_handler import handle_stitch_command

        ns = argparse.Namespace(stitch_subcommand=None)
        with pytest.raises(SystemExit) as excinfo:
            handle_stitch_command(ns)
        assert excinfo.value.code == 2

    def test_log_handler_rejects_invalid_date(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.stitch_handler import _handle_log

        ns = argparse.Namespace(
            all=False,
            limit=20,
            repos=[],
            current_only=False,
            format="pretty",
            color="auto",
            no_fetch=False,
            force_fetch=False,
            merges="hide",
            remote_ref=None,
            reverse=False,
            since="last week",
            show_tags=True,
            until=None,
            authors=[],
        )

        assert _handle_log(ns) == 2
        assert "Accepted DATE forms" in capsys.readouterr().err

    def test_log_handler_rejects_empty_window(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.stitch_handler import _handle_log

        ns = argparse.Namespace(
            all=False,
            limit=20,
            repos=[],
            current_only=False,
            format="pretty",
            color="auto",
            no_fetch=False,
            force_fetch=False,
            merges="hide",
            remote_ref=None,
            reverse=False,
            since="2026-07-09",
            show_tags=True,
            sdd=False,
            until="2026-07-08",
            authors=[],
        )

        assert _handle_log(ns) == 2
        assert "--since/--after" in capsys.readouterr().err

    def test_log_handler_propagates_inclusive_end_of_day_bounds(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.core.time import get_timezone
        from sase.main.stitch_handler import _handle_log
        import sase.vcs_log.collect as collect_module
        import sase.vcs_log.dates as dates_module
        import sase.vcs_log.progress as progress_module
        import sase.vcs_log.render as render_module

        tz = get_timezone()
        reference = datetime(2026, 7, 18, 12, 0, tzinfo=tz)
        captured: dict[str, Any] = {}

        def run_vcs_log(**kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(repos=("sase",))

        monkeypatch.setattr(
            dates_module,
            "normalize_reference_time",
            lambda now=None: reference,
        )
        monkeypatch.setattr(collect_module, "run_vcs_log", run_vcs_log)
        monkeypatch.setattr(progress_module, "make_fetch_progress", lambda _color: None)
        monkeypatch.setattr(render_module, "render", lambda *_args, **_kwargs: None)
        ns = argparse.Namespace(
            all=False,
            authors=[],
            color="auto",
            current_only=False,
            force_fetch=False,
            format="pretty",
            limit=20,
            merges="show",
            no_fetch=True,
            remote_ref=None,
            repos=[],
            reverse=False,
            sdd=False,
            show_tags=True,
            since="2026-07-18",
            until="2026-07-18",
        )

        assert _handle_log(ns) == 0
        filter_spec = captured["filter_spec"]
        assert filter_spec.since is not None
        assert filter_spec.until is not None
        filters = filter_spec.resolve(now=reference)
        assert filters.since == int(datetime(2026, 7, 18, tzinfo=tz).timestamp())
        assert filters.until == int(datetime(2026, 7, 19, tzinfo=tz).timestamp()) - 1
        assert filters.merges == "show"
