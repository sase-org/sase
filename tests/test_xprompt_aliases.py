"""Tests for xprompt alias resolution."""

from unittest.mock import patch

import pytest

from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.project_aliases import (
    canonicalize_project_aliases_in_prompt,
    load_project_alias_map,
    resolve_project_alias_ref,
)
from sase.workspace_provider._hookspec import WorkflowMetadata
from sase.xprompt.processor import resolve_xprompt_aliases


def _mock_config(aliases: dict[str, str]) -> dict:
    return {"xprompt_aliases": aliases}


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    state: str = "active",
    system_managed: bool = False,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=state != "sibling",
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
    )


def _metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="cd",
            ref_pattern=r"(?:^|(?<=\s))#cd(?:[_:]([^\s()]+)|\(([^)]*)\))",
            display_name="Directory",
            pre_allocated_env_prefix="SASE_CD",
        ),
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
            vcs_family="git",
            vcs_provider_name="github",
        ),
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
            vcs_family="git",
            vcs_provider_name="bare_git",
        ),
    )


@pytest.fixture(autouse=True)
def _patch_project_alias_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {},
    )


def test_project_alias_map_loads_all_non_system_non_home_states(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    calls: list[tuple[object, object, bool]] = []

    def fake_list(projects_root, include_states, *, include_home):
        calls.append((projects_root, include_states, include_home))
        return [
            _record("bob-cli", aliases=["bob"]),
            _record("docs-cli", aliases=["docs"], state="inactive"),
            _record("sibling-cli", aliases=["sib"], state="sibling"),
            _record("home", aliases=["h"]),
            _record("managed", aliases=["m"], system_managed=True),
        ]

    monkeypatch.setattr("sase.project_aliases.list_project_records", fake_list)

    assert load_project_alias_map(projects) == {
        "bob": "bob-cli",
        "docs": "docs-cli",
        "sib": "sibling-cli",
    }
    assert calls == [(projects, "all", False)]


def test_project_alias_map_rejects_real_project_name_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob-cli", aliases=["docs"]),
            _record("docs"),
        ],
    )

    with pytest.raises(ValueError, match="real project name"):
        load_project_alias_map(projects)


def test_project_alias_map_rejects_duplicate_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob-cli", aliases=["bob"]),
            _record("docs-cli", aliases=["bob"]),
        ],
    )

    with pytest.raises(ValueError, match="assigned to both"):
        load_project_alias_map(projects)


def test_resolve_project_alias_ref_uses_exact_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )

    assert resolve_project_alias_ref("bob") == "bob-cli"
    assert resolve_project_alias_ref("bbugyi200/bob") == "bbugyi200/bob"
    assert resolve_project_alias_ref("bob-tools") == "bob-tools"


def test_canonicalize_project_aliases_in_prompt_rewrites_vcs_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli", "docs": "docs-cli"},
    )

    prompt = "#gh:bob fix\n#gh_bob more\n#git(docs)\n#gh!!:bob\n#git??_docs"

    assert canonicalize_project_aliases_in_prompt(prompt) == (
        "#gh:bob-cli fix\n"
        "#gh:bob-cli more\n"
        "#git(docs-cli)\n"
        "#gh!!:bob-cli\n"
        "#git??:docs-cli"
    )


def test_canonicalize_project_aliases_in_prompt_rewrites_generated_github_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {
            "foo": "gh_foo_org__foo",
            "foo-2": "gh_bar_org__foo",
        },
    )

    prompt = "#gh:foo fix\n#gh:foo-2 fix\n#gh:foo-org/foo keep"

    assert canonicalize_project_aliases_in_prompt(prompt) == (
        "#gh:gh_foo_org__foo fix\n#gh:gh_bar_org__foo fix\n#gh:foo-org/foo keep"
    )


def test_canonicalize_project_aliases_in_prompt_does_not_rewrite_non_exact_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )

    prompt = (
        "#gh:bbugyi200/bob keep\n"
        "#gh:bob-tools keep\n"
        "#bob keep\n"
        "#cd:bob keep\n"
        "plain bob keep\n"
        "```text\n#gh:bob keep\n```\n"
        "#gh:bob rewrite"
    )

    assert canonicalize_project_aliases_in_prompt(prompt) == (
        "#gh:bbugyi200/bob keep\n"
        "#gh:bob-tools keep\n"
        "#bob keep\n"
        "#cd:bob keep\n"
        "plain bob keep\n"
        "```text\n#gh:bob keep\n```\n"
        "#gh:bob-cli rewrite"
    )


def test_resolve_xprompt_aliases_canonicalizes_project_aliases_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )
    with patch(
        "sase.config.load_merged_config",
        return_value=_mock_config({"gh_bob-cli": "gh:unexpected"}),
    ):
        assert resolve_xprompt_aliases("#gh_bob do it") == "#gh:bob-cli do it"


class TestResolveXpromptAliases:
    """Tests for resolve_xprompt_aliases()."""

    def test_no_aliases_configured(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value={"xprompt_aliases": {}},
        ):
            assert resolve_xprompt_aliases("hello #foo") == "hello #foo"

    def test_missing_aliases_key(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value={},
        ):
            assert resolve_xprompt_aliases("hello #foo") == "hello #foo"

    def test_simple_replacement(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            assert resolve_xprompt_aliases("#gh_sase") == "#gh:sase"

    def test_start_of_line(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase do something")
            assert result == "#gh:sase do something"

    def test_after_whitespace(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("run #gh_sase now")
            assert result == "run #gh:sase now"

    def test_after_open_paren(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("(#gh_sase)")
            assert result == "(#gh:sase)"

    def test_no_match_inside_word(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"foo": "bar"}),
        ):
            # "x#foo" should not match because # is preceded by a letter
            result = resolve_xprompt_aliases("x#foo")
            assert result == "x#foo"

    def test_no_partial_name_match(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh": "github"}),
        ):
            # #gh_sase should NOT be matched by alias "gh" due to negative lookahead
            result = resolve_xprompt_aliases("#gh_sase")
            assert result == "#gh_sase"

    def test_multiple_aliases(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase", "gh_dot": "gh:dotfiles"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase and #gh_dot")
            assert result == "#gh:sase and #gh:dotfiles"

    def test_idempotent(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            first = resolve_xprompt_aliases("#gh_sase")
            second = resolve_xprompt_aliases(first)
            assert first == second == "#gh:sase"

    def test_no_hash_early_return(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("no hash here")
            assert result == "no hash here"

    def test_multiple_occurrences(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase #gh_sase")
            assert result == "#gh:sase #gh:sase"

    def test_after_newline(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("line1\n#gh_sase")
            assert result == "line1\n#gh:sase"
