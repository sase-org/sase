"""Tests for the ``sase vcs`` parser and handler dispatch."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser


class TestVcsParser:
    def test_bare_vcs_defaults_to_list(self) -> None:
        ns = create_parser().parse_args(["vcs"])

        assert ns.command == "vcs"
        assert ns.vcs_subcommand == "list"
        assert ns.repos == []
        assert ns.current_only is False
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.no_fetch is False
        assert ns.sort == "default"

    def test_list_defaults(self) -> None:
        ns = create_parser().parse_args(["vcs", "list"])

        assert ns.vcs_subcommand == "list"
        assert ns.repos == []
        assert ns.current_only is False
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.no_fetch is False
        assert ns.sort == "default"

    def test_list_options(self) -> None:
        ns = create_parser().parse_args(
            [
                "vcs",
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

    def test_log_defaults(self) -> None:
        ns = create_parser().parse_args(["vcs", "log"])

        assert ns.vcs_subcommand == "log"
        assert ns.all is False
        assert ns.limit == 40
        assert ns.authors == []
        assert ns.format == "pretty"
        assert ns.color == "auto"
        assert ns.no_fetch is False
        assert ns.force_fetch is False
        assert ns.remote_ref is None
        assert ns.reverse is False
        assert ns.sdd is False
        assert ns.since is None
        assert ns.show_tags is True
        assert ns.until is None

    def test_log_limit_and_format_and_color(self) -> None:
        ns = create_parser().parse_args(
            ["vcs", "log", "-n", "5", "--format", "full", "--color", "never"]
        )

        assert ns.limit == 5
        assert ns.format == "full"
        assert ns.color == "never"

    def test_log_short_format_and_color_aliases(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "-f", "json", "-c", "never"])

        assert ns.format == "json"
        assert ns.color == "never"

    def test_log_remote_options(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "-b", "main", "-N"])

        assert ns.remote_ref == "main"
        assert ns.no_fetch is True

    def test_log_force_fetch_option(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "-F"])

        assert ns.force_fetch is True
        assert ns.no_fetch is False

    def test_log_fetch_and_no_fetch_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            create_parser().parse_args(["vcs", "log", "--fetch", "--no-fetch"])

        assert excinfo.value.code == 2

    def test_log_ref_alias(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "--ref", "release"])

        assert ns.remote_ref == "release"

    def test_log_repo_is_repeatable(self) -> None:
        ns = create_parser().parse_args(
            ["vcs", "log", "-r", "sase", "--repo", "sase-core"]
        )

        assert ns.repos == ["sase", "sase-core"]

    def test_log_current_only_flag(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "-o"])

        assert ns.current_only is True

    @pytest.mark.parametrize("option", ["-a", "--all"])
    def test_log_all_project_flags(self, option: str) -> None:
        ns = create_parser().parse_args(["vcs", "log", option])

        assert ns.all is True
        assert ns.authors == []

    def test_log_all_and_current_only_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            create_parser().parse_args(["vcs", "log", "--all", "--current-only"])

        assert excinfo.value.code == 2

    def test_log_accepts_limit_zero(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "--limit", "0"])

        assert ns.limit == 0

    def test_log_rejects_negative_limit(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["vcs", "log", "-n", "-1"])

    def test_log_rejects_unknown_format(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["vcs", "log", "--format", "fancy"])

    def test_log_date_aliases_author_and_reverse(self) -> None:
        ns = create_parser().parse_args(
            [
                "vcs",
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

    def test_log_since_until_short_aliases(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "-s", "1d", "-u", "today"])

        assert ns.since == "1d"
        assert ns.until == "today"

    def test_log_no_tags_option(self) -> None:
        short = create_parser().parse_args(["vcs", "log", "-T"])
        long = create_parser().parse_args(["vcs", "log", "--no-tags"])

        assert short.show_tags is False
        assert long.show_tags is False

    @pytest.mark.parametrize("option", ["-S", "--sdd"])
    def test_log_sdd_flags(self, option: str) -> None:
        ns = create_parser().parse_args(["vcs", "log", option])

        assert ns.sdd is True

    def test_log_tags_aliases_remain_hidden_no_ops(self) -> None:
        short = create_parser().parse_args(["vcs", "log", "-t"])
        long = create_parser().parse_args(["vcs", "log", "--tags"])

        assert short.show_tags is True
        assert long.show_tags is True

    def test_log_help_shows_sorted_current_tag_and_fetch_options(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            create_parser().parse_args(["vcs", "log", "-h"])

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


class TestVcsHandlerDispatch:
    def test_unknown_subcommand_exits_2(self) -> None:
        from sase.main.vcs_handler import handle_vcs_command

        ns = argparse.Namespace(vcs_subcommand="bogus")
        with pytest.raises(SystemExit) as excinfo:
            handle_vcs_command(ns)
        assert excinfo.value.code == 2

    def test_missing_subcommand_exits_2(self) -> None:
        from sase.main.vcs_handler import handle_vcs_command

        ns = argparse.Namespace(vcs_subcommand=None)
        with pytest.raises(SystemExit) as excinfo:
            handle_vcs_command(ns)
        assert excinfo.value.code == 2

    def test_log_handler_rejects_invalid_date(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.vcs_handler import _handle_log

        ns = argparse.Namespace(
            limit=20,
            repos=[],
            current_only=False,
            format="pretty",
            color="auto",
            no_fetch=False,
            force_fetch=False,
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
        from sase.main.vcs_handler import _handle_log

        ns = argparse.Namespace(
            limit=20,
            repos=[],
            current_only=False,
            format="pretty",
            color="auto",
            no_fetch=False,
            force_fetch=False,
            remote_ref=None,
            reverse=False,
            since="2026-07-09",
            show_tags=True,
            until="2026-07-08",
            authors=[],
        )

        assert _handle_log(ns) == 2
        assert "--since/--after" in capsys.readouterr().err
