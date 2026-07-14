"""Parser and registry tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import pytest

from sase.main.init_registry import iter_init_command_specs
from sase.main.parser import create_parser


def test_parser_accepts_bare_init_modes() -> None:
    parser = create_parser()

    init_args = parser.parse_args(["init"])
    assert init_args.command == "init"
    assert init_args.init_subcommand is None
    assert init_args.all is False
    assert init_args.yes is False
    assert init_args.check is False
    assert init_args.diff is False
    assert init_args.enable_project_memory is False

    enable_args = parser.parse_args(["init", "--enable-project-memory"])
    assert enable_args.init_subcommand is None
    assert enable_args.enable_project_memory is True

    short_enable_args = parser.parse_args(["init", "-M"])
    assert short_enable_args.enable_project_memory is True

    yes_args = parser.parse_args(["init", "--yes"])
    assert yes_args.init_subcommand is None
    assert yes_args.yes is True

    check_args = parser.parse_args(["init", "--check"])
    assert check_args.init_subcommand is None
    assert check_args.check is True

    short_check_args = parser.parse_args(["init", "-c"])
    assert short_check_args.init_subcommand is None
    assert short_check_args.check is True

    assert parser.parse_args(["init", "--diff"]).diff is True
    assert parser.parse_args(["init", "-d"]).diff is True

    all_args = parser.parse_args(["init", "--all"])
    assert all_args.all is True

    short_all_args = parser.parse_args(["init", "-a"])
    assert short_all_args.all is True

    assert parser.parse_args(["init", "--all", "--check"]).check is True
    assert parser.parse_args(["init", "--all", "--yes"]).yes is True


def test_parser_accepts_scoped_init_check_modes() -> None:
    parser = create_parser()

    repo_short_args = parser.parse_args(["repo", "init", "-c"])
    assert repo_short_args.command == "repo"
    assert repo_short_args.repo_subcommand == "init"
    assert repo_short_args.check is True

    repo_long_args = parser.parse_args(["repo", "init", "--check"])
    assert repo_long_args.check is True
    assert parser.parse_args(["repo", "init", "-d"]).diff is True

    memory_short_args = parser.parse_args(["memory", "init", "-c"])
    assert memory_short_args.command == "memory"
    assert memory_short_args.memory_subcommand == "init"
    assert memory_short_args.check is True
    assert memory_short_args.no_commit is False
    assert memory_short_args.enable_project_memory is False

    memory_enable_args = parser.parse_args(
        ["memory", "init", "--enable-project-memory"]
    )
    assert memory_enable_args.enable_project_memory is True

    memory_long_args = parser.parse_args(["memory", "init", "--check"])
    assert memory_long_args.check is True
    assert parser.parse_args(["memory", "init", "--diff"]).diff is True

    init_repo_args = parser.parse_args(["init", "repo", "--check"])
    assert init_repo_args.command == "init"
    assert init_repo_args.init_subcommand == "repo"
    assert init_repo_args.check is True
    assert parser.parse_args(["init", "repo", "-d"]).diff is True
    assert parser.parse_args(["init", "repo", "-C"]).no_commit is True

    init_memory_args = parser.parse_args(["init", "memory", "--check"])
    assert init_memory_args.command == "init"
    assert init_memory_args.init_subcommand == "memory"
    assert init_memory_args.check is True
    assert parser.parse_args(["init", "memory", "--diff"]).diff is True

    init_memory_enable_args = parser.parse_args(["init", "memory", "-M"])
    assert init_memory_enable_args.enable_project_memory is True

    parent_repo_args = parser.parse_args(["init", "--check", "repo"])
    assert parent_repo_args.init_subcommand == "repo"
    assert parent_repo_args.check is True
    assert parser.parse_args(["init", "--diff", "repo"]).diff is True

    parent_memory_args = parser.parse_args(["init", "--check", "memory"])
    assert parent_memory_args.init_subcommand == "memory"
    assert parent_memory_args.check is True
    assert parser.parse_args(["init", "--diff", "memory"]).diff is True

    skill_short_args = parser.parse_args(["skill", "init", "-c"])
    assert skill_short_args.command == "skill"
    assert skill_short_args.skill_subcommand == "init"
    assert skill_short_args.check is True

    skill_long_args = parser.parse_args(["skill", "init", "--check"])
    assert skill_long_args.check is True
    assert parser.parse_args(["skill", "init", "-d"]).diff is True

    init_skills_args = parser.parse_args(["init", "skills", "--check"])
    assert init_skills_args.command == "init"
    assert init_skills_args.init_subcommand == "skills"
    assert init_skills_args.check is True
    assert parser.parse_args(["init", "skills", "--diff"]).diff is True

    parent_skills_args = parser.parse_args(["init", "--check", "skills"])
    assert parent_skills_args.init_subcommand == "skills"
    assert parent_skills_args.check is True
    assert parser.parse_args(["init", "--diff", "skills"]).diff is True

    with pytest.raises(SystemExit):
        parser.parse_args(["init", "sdd"])
    with pytest.raises(SystemExit):
        parser.parse_args(["init", "workspace"])


def test_parser_rejects_bare_init_check_yes_conflict() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["init", "--check", "--yes"])

    check_args = parser.parse_args(["init", "--check"])
    assert check_args.check is True
    assert check_args.yes is False

    yes_args = parser.parse_args(["init", "--yes"])
    assert yes_args.check is False
    assert yes_args.yes is True


def test_parser_rejects_all_project_memory_opt_in() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["init", "--all", "--enable-project-memory"])


def test_init_help_lists_existing_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["init", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "amd" not in out
    assert "memory" in out
    assert "repo" in out
    assert "skills" in out
    assert "workspace" not in out
    assert "-a, --all" in out
    assert "-c, --check" in out
    assert "-d, --diff" in out
    assert "-M, --enable-project-memory" in out
    assert "is_sase_managed:" in out
    assert "Advanced deploy controls live on explicit subcommands" in out
    assert "enabled main SASE project" in out
    assert out.index("-a, --all") < out.index("-c, --check")
    assert out.index("-c, --check") < out.index("-d, --diff")
    assert out.index("-d, --diff") < out.index("-M, --enable-project-memory")
    assert out.index("-M, --enable-project-memory") < out.index("-y, --yes")


def test_registry_order_is_memory_repo_skills() -> None:
    assert tuple(spec.name for spec in iter_init_command_specs()) == (
        "memory",
        "repo",
        "skills",
    )
