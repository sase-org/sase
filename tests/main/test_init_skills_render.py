"""Tests for ``sase init skills`` skill-frame rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from sase.main import init_skills_handler
from sase.main import _init_skills_rendering as skills_rendering
from sase.markdown_width import markdown_print_width


def test_skill_frame_default_render_is_stable() -> None:
    rendered = skills_rendering._build_output("demo", "A demo skill.", "Body.\n")

    assert rendered.startswith("---\nname: demo\ndescription: A demo skill.\n---\n\n")
    assert rendered.endswith(
        '```bash\nsase skill use demo --reason "<one-line reason for using this '
        'skill>"\n```\n\nBody.\n'
    )
    # The audit directive is prose wrapped at the repo Markdown width, so match
    # it on collapsed whitespace rather than pinning where it breaks.
    assert (
        "Before doing anything else, run this command to record that you are "
        "using this skill:"
    ) in " ".join(rendered.split())
    assert (
        skills_rendering._build_output(
            "demo", "A demo skill.", "Body.\n", log_skill_use=False
        )
        == "---\nname: demo\ndescription: A demo skill.\n---\n\nBody.\n"
    )
    long_description = (
        "This is a deliberately long generated skill description that exceeds the "
        "repo Markdown prose width so the existing wrapped YAML serialization path "
        "is exercised without changing its output."
    )
    long_output = skills_rendering._build_output(
        "long", long_description, "Body.\n", log_skill_use=False
    )

    assert long_output.startswith("---\nname: long\ndescription:\n  ")
    assert long_output.endswith("---\n\nBody.\n")
    assert yaml.safe_load(long_output.split("---\n")[1])["description"] == (
        long_description
    )
    assert all(len(line) <= markdown_print_width() for line in long_output.split("\n"))
    colon_description = (
        "This is a deliberately long generated skill description whose YAML needs "
        "a block scalar because it contains a mapping-like value: linked repos and "
        "external repos must remain part of the description."
    )
    colon_output = skills_rendering._build_output(
        "colon", colon_description, "Body.\n", log_skill_use=False
    )
    assert "description: >-\n" in colon_output
    assert skills_rendering._validate_skill_frame(colon_output) is None
    assert skills_rendering._build_output(
        "multi", "First line.\nSecond line.", "Body.\n", log_skill_use=False
    ) == (
        "---\nname: multi\ndescription: |\n  First line.\n  Second line.\n"
        "---\n\nBody.\n"
    )


def test_rendered_skill_targets_include_audit_directive_for_each_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompt = init_skills_handler.XPrompt(
        name="skill/foo",
        content="body\n",
        description="a test skill",
        skill=["claude", "codex"],
        skill_name="foo",
    )
    monkeypatch.setattr(
        init_skills_handler,
        "_all_providers",
        lambda: ["claude", "codex"],
    )
    monkeypatch.setattr(init_skills_handler, "_provider_context", lambda _provider: {})
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert {target.provider for target in targets} == {"claude", "codex"}
    for target in targets:
        content = target.content
        directive = (
            'sase skill use foo --reason "<one-line reason for using this skill>"'
        )
        assert directive in content
        assert content.index(directive) < content.index("body")


def test_rendered_skill_targets_omit_audit_directive_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A skill with ``log_skill_use=False`` renders without the audit directive."""
    xprompt = init_skills_handler.XPrompt(
        name="skill/foo",
        content="body\n",
        description="a test skill",
        skill=["claude"],
        log_skill_use=False,
        skill_name="foo",
    )
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])
    monkeypatch.setattr(init_skills_handler, "_provider_context", lambda _provider: {})
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert targets
    for target in targets:
        assert "sase skill use" not in target.content
        assert "body" in target.content


def test_packaged_skills_respect_log_skill_use_flag() -> None:
    """Packaged unaudited skills omit the directive; other skills keep it."""
    from sase.xprompt.loader import load_skills_from_package

    packaged = load_skills_from_package()
    plan_xp = packaged.get("skill/sase_plan")
    memory_xp = packaged.get("skill/sase_memory_read")
    repo_xp = packaged.get("skill/sase_repo")
    project_xp = packaged.get("skill/sase_project")
    artifact_file_xp = packaged.get("skill/sase_artifact_file")
    assert plan_xp is not None
    assert memory_xp is not None
    assert repo_xp is not None
    assert project_xp is not None
    assert artifact_file_xp is not None

    assert plan_xp.log_skill_use is False
    assert memory_xp.log_skill_use is False
    assert repo_xp.log_skill_use is False
    assert project_xp.log_skill_use is True
    assert artifact_file_xp.log_skill_use is True

    targets = init_skills_handler.render_skill_targets(
        [plan_xp, memory_xp, repo_xp, project_xp, artifact_file_xp],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert targets, "expected rendered targets for registered providers"
    for target in targets:
        if target.skill_name in {"sase_artifact_file", "sase_project"}:
            assert f"sase skill use {target.skill_name}" in target.content
        else:
            assert "sase skill use" not in target.content


def test_generated_names_and_paths_ignore_the_skill_reference_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``skill/`` rename is xprompt-side only; ``/foo`` output is unchanged."""
    xprompt = init_skills_handler.XPrompt(
        name="app/skill/foo",
        content="body\n",
        description="a test skill",
        skill=["claude"],
        skill_name="foo",
    )
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])
    monkeypatch.setattr(init_skills_handler, "_provider_context", lambda _provider: {})
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert [target.skill_name for target in targets] == ["foo"]
    for target in targets:
        assert target.path == tmp_path / "home/.claude/skills/foo/SKILL.md"
        assert target.content.startswith("---\nname: foo\n")
        assert "skill/foo" not in target.content.splitlines()[1]
