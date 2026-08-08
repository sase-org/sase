from __future__ import annotations

from pathlib import Path

import pytest

from sase.sidecar_ref_config import DEFAULT_DOCUMENT_REF_PATH_GLOBS, SidecarRefPolicy
from sase.xprompt import loader_refs
from sase.xprompt.load_issues import collect_xprompt_load_issues
from sase.xprompt.models import InputType, XPrompt


def _write_ref(path: Path, *, body: str, ref: str = "true") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ndescription: {path.stem} renderer\nref: {ref}\n---\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def no_sidecar_or_plugin_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader_refs, "_sidecar_policies", lambda _root: ())
    monkeypatch.setattr(loader_refs, "_plugin_ref_candidates", lambda: iter(()))


def test_ref_registry_loads_packaged_refs_and_project_shadowing(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace"
    home_root = tmp_path / "home"
    project_root.mkdir()
    home_root.mkdir()
    project_file = project_root / "sase" / "refs" / "file.md"
    home_file = home_root / "sase" / "refs" / "file.md"
    _write_ref(project_file, body="Project {{ file_path }}")
    _write_ref(home_file, body="Home {{ file_path }}")

    refs = loader_refs.load_ref_xprompts(
        project_root=project_root,
        home_root=home_root,
        project="demo",
    )

    assert {
        "ref/commit",
        "ref/chat",
        "ref/bug",
        "ref/file",
        "ref/bead",
        "ref/agent",
    } <= set(refs)
    file_ref = refs["ref/file"]
    assert file_ref.ref is True
    assert file_ref.ref_kind == "file"
    assert file_ref.content.strip() == "Project {{ file_path }}"
    assert file_ref.source_path == str(project_file)
    assert file_ref.inputs[0].name == "artifact_id"
    assert file_ref.inputs[0].type == InputType.LINE
    assert str(home_file) in file_ref.ref_shadowed_sources
    assert any(
        source.endswith("/xprompts/refs/file.md")
        for source in file_ref.ref_shadowed_sources
    )


def test_ref_registry_uses_sidecar_config_before_generated_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policies = (
        SidecarRefPolicy(
            role="research",
            ref_kind="research",
            is_document=True,
            xprompt="Configured {{ file_path }}",
            path_globs=("reports/**/*.md",),
        ),
        SidecarRefPolicy(
            role="designs",
            ref_kind="designs",
            is_document=True,
            path_globs=DEFAULT_DOCUMENT_REF_PATH_GLOBS,
        ),
    )
    monkeypatch.setattr(loader_refs, "_sidecar_policies", lambda _root: policies)

    refs = loader_refs.load_ref_xprompts(
        project_root=tmp_path / "workspace",
        home_root=tmp_path / "home",
        project="demo",
    )

    research = refs["ref/research"]
    assert research.content.strip() == "Configured {{ file_path }}"
    assert research.source_path == "sidecar_ref_config:research"
    assert research.ref_sidecar_role == "research"
    assert research.ref_path_globs == ("reports/**/*.md",)
    assert "generated_sidecar_ref:research" in research.ref_shadowed_sources

    designs = refs["ref/designs"]
    assert (
        designs.content.strip()
        == "the {{ file_path }} file in the {{ sidecar }} sidecar repo"
    )
    assert designs.source_path == "generated_sidecar_ref:designs"
    assert designs.ref_path_globs == DEFAULT_DOCUMENT_REF_PATH_GLOBS


def test_ref_metadata_is_rejected_outside_ref_sources(tmp_path: Path) -> None:
    source = tmp_path / "sase" / "xprompts" / "ordinary.md"

    with collect_xprompt_load_issues() as issues:
        rejected = loader_refs.reject_misplaced_ref(
            XPrompt(name="ordinary", content="", ref=True),
            source=source,
        )

    assert rejected is True
    assert [(issue.kind, issue.source) for issue in issues] == [
        ("ref", str(source)),
    ]
    assert "refs/ source directory" in issues[0].error
