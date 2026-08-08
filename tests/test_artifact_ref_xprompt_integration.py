from __future__ import annotations

from pathlib import Path

import pytest

from sase import artifact_ref_prompt
from sase.ace.tui.widgets.artifact_ref_completion import (
    build_artifact_ref_completion_result,
    build_ref_xprompt_arg_completion_result,
    detect_artifact_ref_completion_context,
    load_artifact_ref_completion_catalog,
)
from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    process_artifact_references,
    validate_artifact_references,
)


@pytest.fixture(autouse=True)
def _disable_consumption_ledger_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda _events: None,
    )


def _write_document(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tier: tale\n"
        "create_time: 2026-08-08 12:00:00\n"
        "status: wip\n"
        "---\n"
        f"# {title}\n\n"
        "Body.\n",
        encoding="utf-8",
    )


def _context(
    tmp_path: Path,
    *,
    path_globs: tuple[str, ...] | None = ("**/*.md",),
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot(
                "research",
                tmp_path / "research",
                path_globs=path_globs,
            ),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(
            ArtifactRefProject(name="alpha", key="gh_example__alpha"),
            ArtifactRefProject(name="sase", key="gh_sase-org__sase"),
        ),
        selected_project="sase",
    )


def test_research_ref_forms_share_rendering_staging_consumption_and_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    relpath = "202608/artifact_reference_rendering/artifact_reference_rendering.md"
    hidden = "secret/hidden.md"
    research_root = tmp_path / "research"
    _write_document(research_root / relpath, "Artifact Reference Rendering")
    _write_document(research_root / hidden, "Hidden Research")
    context = _context(tmp_path, path_globs=("**/*.md", "!secret/**"))
    staged: list[dict[str, object]] = []
    recorded: list[object] = []
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.stage_prompt_artifact",
        lambda **kwargs: staged.append(kwargs) or kwargs,
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    direct = process_artifact_references(f"@research:{relpath}", context=context)
    explicit = process_artifact_references(f"#ref/research:{relpath}", context=context)

    expected = f"the {relpath} file in the research sidecar repo"
    resolved = research_root / relpath
    assert direct == explicit == expected
    assert [row["raw_ref"] for row in staged] == [
        f"@research:{relpath}",
        f"#ref/research:{relpath}",
    ]
    assert [row["expanded_ref"] for row in staged] == [expected, expected]
    assert [row["resolved_path"] for row in staged] == [resolved, resolved]
    assert [row["ref_kind"] for row in staged] == ["research", "research"]
    assert [event.ref for event in recorded] == [
        f"research:{relpath}",
        f"research:{relpath}",
    ]
    assert [event.resolved_path for event in recorded] == [str(resolved), str(resolved)]
    assert [event.ref_kind for event in recorded] == ["research", "research"]
    assert [event.role for event in recorded] == ["report", "report"]

    catalog = load_artifact_ref_completion_catalog("sase", context)
    at_context = detect_artifact_ref_completion_context(
        "@research:",
        len("@research:"),
        context.known_kinds,
    )
    assert at_context is not None
    at_result = build_artifact_ref_completion_result(at_context, catalog)
    ref_result = build_ref_xprompt_arg_completion_result("research", "", catalog)
    assert ref_result is not None

    at_insertions = [candidate.insertion for candidate in at_result.candidates]
    ref_insertions = [candidate.insertion for candidate in ref_result.candidates]
    assert at_insertions == [f"@research:{relpath}"]
    assert ref_insertions == [relpath]
    assert hidden not in " ".join((*at_insertions, *ref_insertions))

    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(f"@research:{hidden}", context=context)
    output = capsys.readouterr().out
    assert "filtered" in output
    assert hidden in output


def test_research_filters_can_opt_into_non_markdown_and_disabled_sidecar_is_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    research_root = tmp_path / "research"
    image = research_root / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(
            "@research:diagram.png",
            context=_context(tmp_path),
        )
    output = capsys.readouterr().out
    assert "filtered" in output
    assert "diagram.png" in output

    assert (
        process_artifact_references(
            "#ref/research:diagram.png",
            context=_context(tmp_path, path_globs=("**/*.png",)),
        )
        == "the diagram.png file in the research sidecar repo"
    )

    disabled_context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject(name="sase", key="gh_sase-org__sase"),),
        selected_project="sase",
    )
    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(
            "#ref/research:diagram.png",
            context=disabled_context,
        )
    output = capsys.readouterr().out
    assert "unknown_kind" in output
    assert "#ref/research:diagram.png" in output
