from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase import artifact_ref_prompt
from sase.artifact_refs import (
    ArtifactRendererJinjaProtection,
    ArtifactRefProject,
    process_artifact_references,
)
from sase.xprompt.models import InputArg, InputType, XPrompt

from .preprocessing_helpers import (
    context as make_context,
    disable_consumption_ledger_writes,  # noqa: F401 (registers autouse fixture)
    sidecar_sentence,
)


def test_ref_xprompt_colon_and_named_forms_match_artifact_reference(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")

    expected = sidecar_sentence("plans", "report.md")

    assert process_artifact_references("@plans:report.md", context=context) == expected
    assert (
        process_artifact_references("#ref/plans:report.md", context=context) == expected
    )
    assert (
        process_artifact_references(
            "#ref/plans(file_path=report.md)",
            context=context,
        )
        == expected
    )


def test_ref_renderer_receives_primitive_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    renderer = XPrompt(
        name="ref/plans",
        content=(
            "{{ sidecar }}|{{ file_path }}|{{ ref.raw }}|"
            "{{ ref.canonical }}|{{ ref.kind_type }}"
        ),
        inputs=[InputArg("file_path", InputType.PATH)],
        ref=True,
        ref_kind="plans",
        ref_sidecar_role="plans",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "ref_renderer_registry",
        lambda _context: {"ref/plans": renderer},
    )

    assert (
        process_artifact_references("#ref/plans:report.md", context=context)
        == "plans|report.md|#ref/plans:report.md|@plans:report.md|document"
    )


def test_ref_renderer_context_uses_selected_project_with_multi_project_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = replace(
        make_context(tmp_path),
        projects=(
            ArtifactRefProject(name="alpha", key="gh_example__alpha"),
            ArtifactRefProject(name="sase", key="gh_sase-org__sase"),
        ),
        selected_project="sase",
    )
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    renderer = XPrompt(
        name="ref/plans",
        content="{{ ref.project }}|{{ sidecar }}|{{ file_path }}",
        inputs=[InputArg("file_path", InputType.PATH)],
        ref=True,
        ref_kind="plans",
        ref_sidecar_role="plans",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "ref_renderer_registry",
        lambda _context: {"ref/plans": renderer},
    )

    assert (
        process_artifact_references("#ref/plans:report.md", context=context)
        == "sase|plans|report.md"
    )


def test_renderer_output_is_not_recursively_scanned_for_artifact_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    for name in ("report.md", "other.md"):
        path = tmp_path / "plans" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Report\n", encoding="utf-8")
    renderer = XPrompt(
        name="ref/plans",
        content="@plans:other.md",
        inputs=[InputArg("file_path", InputType.PATH)],
        ref=True,
        ref_kind="plans",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "ref_renderer_registry",
        lambda _context: {"ref/plans": renderer},
    )

    assert (
        process_artifact_references("@plans:report.md", context=context)
        == "@plans:other.md"
    )


def test_renderer_jinja_output_is_protected_from_top_level_jinja(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.xprompt import render_toplevel_jinja2

    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    renderer = XPrompt(
        name="ref/plans",
        content="literal {% raw %}{{ missing }}{% endraw %} for {{ file_path }}",
        inputs=[InputArg("file_path", InputType.PATH)],
        ref=True,
        ref_kind="plans",
    )
    protection = ArtifactRendererJinjaProtection()
    monkeypatch.setattr(
        artifact_ref_prompt,
        "ref_renderer_registry",
        lambda _context: {"ref/plans": renderer},
    )

    expanded = process_artifact_references(
        "Before {{ 1 + 1 }} @plans:report.md.",
        context=context,
        jinja_protection=protection,
    )
    rendered = render_toplevel_jinja2(expanded)

    assert protection.unprotect(rendered) == (
        "Before 2 literal {{ missing }} for report.md."
    )


def test_renderer_undefined_variable_failure_names_kind_and_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    renderer = XPrompt(
        name="ref/plans",
        content="{{ missing }}",
        inputs=[InputArg("file_path", InputType.PATH)],
        source_path="test-renderer.md",
        ref=True,
        ref_kind="plans",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "ref_renderer_registry",
        lambda _context: {"ref/plans": renderer},
    )

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references("@plans:report.md", context=context)

    output = capsys.readouterr().out
    assert "@plans:report.md" in output
    assert "renderer" in output
    assert "ref/plans renderer error in test-renderer.md" in output
