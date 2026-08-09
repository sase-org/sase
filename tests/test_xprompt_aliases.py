"""Tests for xprompt alias resolution."""

from pathlib import Path
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
    state: str = "enabled",
    system_managed: bool = False,
    project_file: str | Path | None = None,
    archive_file: str | Path | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=str(
            project_file or f"/tmp/projects/{project_name}/{project_name}.sase"
        ),
        archive_file=str(archive_file) if archive_file is not None else None,
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


def _write_project_spec(
    projects_root: Path,
    project_name: str,
    *,
    changespec_names: tuple[str, ...] = (),
    archive: bool = False,
) -> Path:
    suffix = "-archive" if archive else ""
    project_file = projects_root / project_name / f"{project_name}{suffix}.sase"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    content = "" if archive else f"WORKSPACE_DIR: /tmp/{project_name}\n"
    content += "".join(
        f"NAME: {name}\nDESCRIPTION:\nSTATUS: WIP\n\n" for name in changespec_names
    )
    project_file.write_text(content, encoding="utf-8")
    return project_file


def _metadata() -> tuple[WorkflowMetadata, ...]:
    return (
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
def _patch_project_alias_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.workspace_provider._registry as registry

    projects_root = tmp_path / "canonicalize-projects"
    projects_root.mkdir()
    monkeypatch.setattr(registry, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(
        "sase.project_aliases.sase_projects_dir",
        lambda: projects_root,
    )
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
            _record(
                "bob-cli",
                aliases=["bob"],
                project_file=_write_project_spec(projects, "bob-cli"),
            ),
            _record(
                "docs-cli",
                aliases=["docs"],
                state="disabled",
                project_file=_write_project_spec(projects, "docs-cli"),
            ),
            _record(
                "sibling-cli",
                aliases=["sib"],
                state="sibling",
                project_file=_write_project_spec(projects, "sibling-cli"),
            ),
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


def test_project_alias_map_drops_alias_shadowed_by_real_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "bob-cli",
                aliases=["docs"],
                project_file=_write_project_spec(projects, "bob-cli"),
            ),
            _record("docs", project_file=_write_project_spec(projects, "docs")),
        ],
    )

    # The shadowed alias self-resolves instead of crashing read paths.
    assert load_project_alias_map(projects) == {}
    assert resolve_project_alias_ref("docs", projects) == "docs"


def test_project_alias_map_drops_duplicate_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "bob-cli",
                aliases=["bob"],
                project_file=_write_project_spec(projects, "bob-cli"),
            ),
            _record(
                "docs-cli",
                aliases=["bob"],
                project_file=_write_project_spec(projects, "docs-cli"),
            ),
        ],
    )

    # An ambiguous alias maps to neither claimant so it self-resolves.
    assert load_project_alias_map(projects) == {}
    assert resolve_project_alias_ref("bob", projects) == "bob"


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


def test_resolve_project_alias_ref_accepts_exact_owner_repo_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase-org/sase": "sase"},
    )

    assert resolve_project_alias_ref("sase-org/sase") == "sase"
    assert resolve_project_alias_ref("other-org/sase") == "other-org/sase"


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


def test_canonicalize_project_aliases_in_prompt_rewrites_owner_repo_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase-org/sase": "sase"},
    )

    assert canonicalize_project_aliases_in_prompt("#gh:sase-org/sase fix") == (
        "#gh:sase fix"
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


def test_canonicalize_preserves_literal_display_prefixed_patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "gh_sase-org__sase"},
    )
    _write_project_spec(
        projects_root,
        "gh_sase-org__sase",
        changespec_names=("sase_fix_just_linters_14",),
    )

    assert (
        canonicalize_project_aliases_in_prompt("#gh:sase_fix_just_linters_14 review")
        == "#gh:sase_fix_just_linters_14 review"
    )


def test_canonicalize_keeps_legacy_prefix_rewrite_without_literal_changespec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "gh_sase-org__sase"},
    )

    assert canonicalize_project_aliases_in_prompt("#gh:sase_legacy_fix review") == (
        "#gh:gh_sase-org__sase_legacy_fix review"
    )


def test_canonicalize_preserves_literal_archived_patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "gh_sase-org__sase"},
    )
    _write_project_spec(
        projects_root,
        "gh_sase-org__sase",
        changespec_names=("sase_archived_fix",),
        archive=True,
    )

    assert canonicalize_project_aliases_in_prompt("#gh:sase_archived_fix resume") == (
        "#gh:sase_archived_fix resume"
    )


def test_canonicalize_repairs_previously_mangled_patch_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "gh_sase-org__sase"},
    )
    _write_project_spec(
        projects_root,
        "gh_sase-org__sase",
        changespec_names=("sase_fix_just_linters_14",),
    )

    assert (
        canonicalize_project_aliases_in_prompt(
            "#gh:gh_sase-org__sase_fix_just_linters_14 review"
        )
        == "#gh:sase_fix_just_linters_14 review"
    )


def test_canonicalize_does_not_repair_resolvable_compound_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "gh_sase-org__sase"},
    )
    _write_project_spec(
        projects_root,
        "gh_sase-org__sase",
        changespec_names=("fix_just_linters_14", "sase_fix_just_linters_14"),
    )

    assert (
        canonicalize_project_aliases_in_prompt(
            "#gh:gh_sase-org__sase_fix_just_linters_14 review"
        )
        == "#gh:gh_sase-org__sase_fix_just_linters_14 review"
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
        "plain bob keep\n"
        "```text\n#gh:bob keep\n```\n"
        "#gh:bob rewrite"
    )

    assert canonicalize_project_aliases_in_prompt(prompt) == (
        "#gh:bbugyi200/bob keep\n"
        "#gh:bob-tools keep\n"
        "#bob keep\n"
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
