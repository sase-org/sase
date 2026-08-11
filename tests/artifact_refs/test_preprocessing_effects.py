from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
import sase_core_rs

from sase import artifact_ref_prompt
from sase.artifact_refs import (
    ArtifactRefFileRoot,
    process_artifact_references,
    validate_artifact_references,
)
from sase.file_references import process_file_references
from sase.llm_provider.preprocessing import preprocess_prompt_late

from .preprocessing_helpers import (
    context as make_context,
    disable_consumption_ledger_writes,  # noqa: F401 (registers autouse fixture)
)


def test_rewrite_records_one_edge_per_expanded_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    chat = tmp_path / "chats" / "agent.md"
    plan.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "Read @plans:report.md and @chat:agent.md.",
        context=context,
    )

    assert [event.ref for event in recorded] == [
        "plan:report.md",
        "chat:agent.md",
    ]
    assert [event.ref_kind for event in recorded] == ["plan", "chat"]
    assert [event.role for event in recorded] == ["report", "report"]
    assert [event.resolved_path for event in recorded] == [
        str(plan),
        str(chat),
    ]


def test_rewrite_stages_the_same_resolved_reference_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.stage_prompt_artifact",
        lambda **kwargs: staged.append(kwargs),
    )

    process_artifact_references("Read @plans:report.md.", context=context)

    assert staged == [
        {
            "raw_ref": "@plans:report.md",
            "expanded_ref": f"@{plan}",
            "resolved_path": plan,
            "ref_kind": "plan",
            "label": "report.md",
            "locator": None,
        }
    ]


def test_home_mode_does_not_stage_artifact_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.stage_prompt_artifact",
        lambda **kwargs: staged.append(kwargs),
    )

    process_artifact_references(
        "Read @plans:report.md.",
        context=context,
        is_home_mode=True,
    )

    assert staged == []


def test_artifact_expansion_is_not_restaged_as_plain_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "run"))
    staged_paths: set[str] = set()

    expanded = process_artifact_references(
        "Read @plans:report.md.",
        context=context,
        staged_file_paths=staged_paths,
    )
    process_file_references(expanded, staged_file_paths=staged_paths)

    manifest = tmp_path / ".sase/artifacts/prompt-artifacts.jsonl"
    rows = sase_core_rs.prompt_artifact_manifest_parse(manifest.read_bytes())
    assert len(rows) == 1
    assert rows[0]["raw_ref"] == "@plans:report.md"


def test_file_ref_expands_to_captured_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "bob"
    root.mkdir()
    source = root / "gtd.md"
    source.write_text("tasks", encoding="utf-8")
    context = replace(
        make_context(tmp_path),
        file_roots=(ArtifactRefFileRoot("bob", root),),
        home_dir=tmp_path,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "run"))
    staged_paths: set[str] = set()

    expanded = process_artifact_references(
        f"Read @file:{source}.",
        context=context,
        staged_file_paths=staged_paths,
    )

    assert str(source) not in expanded
    assert ".sase/artifacts/pool" in expanded
    captured_path = next(iter(staged_paths))
    assert Path(captured_path).read_text(encoding="utf-8") == "tasks"
    rows = sase_core_rs.prompt_artifact_manifest_parse(
        (tmp_path / ".sase/artifacts/prompt-artifacts.jsonl").read_bytes()
    )
    assert len(rows) == 1
    assert rows[0]["origin"] == "ref"
    assert rows[0]["logical_path"] == "bob:gtd.md"


def test_fragment_is_recorded_separately_from_fragment_free_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@plans:report.md#L2-L4",
        context=context,
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "plan:report.md"
    assert recorded[0].fragment == "L2-L4"


def test_bug_payload_hash_is_preserved_in_recorded_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "_resolved_bug_url",
        lambda project, number: f"https://bugs.test/{project}/{number}",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@bug:gh_sase-org__sase#42",
        context=make_context(tmp_path),
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "bug:gh_sase-org__sase#42"
    assert recorded[0].fragment is None
    assert recorded[0].role == "source"


def test_duplicate_refs_in_one_prompt_record_one_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@plans:report.md and @plans:report.md#L2",
        context=context,
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "plan:report.md"


def test_validation_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    append_calls = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: append_calls.append(tuple(events)),
    )

    validate_artifact_references("@plans:report.md", context=context)

    assert append_calls == []


def test_failed_expansion_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    append_calls = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: append_calls.append(tuple(events)),
    )

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@plans:missing.md",
            context=make_context(tmp_path),
        )

    assert append_calls == []


def test_recorder_failure_does_not_change_expansion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")

    def fail(_events: object) -> None:
        raise OSError("ledger unavailable")

    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        fail,
    )

    assert (
        process_artifact_references(
            "Read @plans:report.md.",
            context=context,
        )
        == f"Read @{plan}."
    )


def test_late_preprocessing_expands_artifacts_before_file_refs() -> None:
    seen: list[tuple[str, bool]] = []

    def expand(
        prompt: str,
        *,
        is_home_mode: bool,
        ref_contexts: object = None,
        staged_file_paths: set[str],
        jinja_protection: object,
    ) -> str:
        assert jinja_protection is not None
        assert staged_file_paths == set()
        seen.append(("artifact", is_home_mode))
        return prompt.replace("@plans:x.md", "@/resolved/x.md")

    def process(
        prompt: str,
        *,
        is_home_mode: bool,
        staged_file_paths: set[str],
    ) -> str:
        assert staged_file_paths == set()
        seen.append(("file", is_home_mode))
        assert "@/resolved/x.md" in prompt
        return prompt

    with (
        patch(
            "sase.artifact_refs.process_artifact_references",
            side_effect=expand,
        ),
        patch(
            "sase.file_references.process_file_references",
            side_effect=process,
        ),
    ):
        preprocess_prompt_late(
            "@plans:x.md",
            is_home_mode=True,
        )

    assert seen == [("artifact", True), ("file", True)]
