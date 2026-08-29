from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.memory.read_log import (
    AgentIdentity,
    AgentIdentityError,
    MemoryReadPathError,
    append_memory_read_event,
    build_memory_read_batch_event,
    build_memory_read_event,
    discover_agent_identity,
    filter_memory_read_events,
    memory_read_log_path,
    read_memory_content,
    read_memory_read_events,
    require_agent_identity,
    strip_leading_frontmatter,
    summarize_memory_reads_by_agent,
    summarize_memory_reads_by_path,
    validate_memory_read_path,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _long_note(body: str = "# Foo\n", *, description: str = "Foo.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def test_validate_memory_read_path_allows_flat_long_markdown(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note())

    result = validate_memory_read_path("foo.md", project_root=tmp_path)

    assert result.canonical_path == "foo.md"
    assert result.path == tmp_path / "sase" / "memory" / "foo.md"
    assert result.note.relative_path == "sase/memory/foo.md"
    assert result.note.type == "reference"
    assert result.resolved_path == (tmp_path / "sase" / "memory" / "foo.md").resolve()


def test_validate_memory_read_path_accepts_optional_memory_prefix(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Foo.\n---\n# Foo\n",
    )

    result = validate_memory_read_path("sase/memory/foo.md", project_root=tmp_path)

    assert result.canonical_path == "foo.md"
    assert result.path == tmp_path / "sase" / "memory" / "foo.md"


def test_validate_memory_read_path_reads_legacy_tree_as_compatibility_fallback(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "memory" / "foo.md", _long_note())

    result = validate_memory_read_path("foo.md", project_root=tmp_path)

    assert result.path == tmp_path / "memory" / "foo.md"
    assert result.note.relative_path == "sase/memory/foo.md"


def test_validate_memory_read_path_rejects_canonical_legacy_collision(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note())
    _write(tmp_path / "memory" / "foo.md", _long_note())

    with pytest.raises(MemoryReadPathError, match="multiple canonical/legacy"):
        validate_memory_read_path("foo.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_nested_legacy_long_markdown(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "long" / "foo.md", _long_note())

    with pytest.raises(MemoryReadPathError, match="flat"):
        validate_memory_read_path("long/foo.md", project_root=tmp_path)


def test_validate_memory_read_path_prefers_project_over_home(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / "sase" / "memory" / "foo.md", _long_note("# Project\n"))
    _write(home / "sase" / "memory" / "foo.md", _long_note("# Home\n"))

    result = validate_memory_read_path(
        "foo.md",
        project_root=project,
        home_root=home,
    )

    assert result.path == project / "sase" / "memory" / "foo.md"
    assert result.resolved_path == (project / "sase" / "memory" / "foo.md").resolve()


def test_validate_memory_read_path_falls_back_to_home(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(home / "sase" / "memory" / "foo.md", _long_note("# Home\n"))

    result = validate_memory_read_path(
        "foo.md",
        project_root=project,
        home_root=home,
    )

    assert result.memory_root == home / "sase" / "memory"
    assert result.path == home / "sase" / "memory" / "foo.md"
    assert result.resolved_path == (home / "sase" / "memory" / "foo.md").resolve()


def test_validate_memory_read_path_dedupes_project_and_home_roots(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note())

    result = validate_memory_read_path(
        "foo.md",
        project_root=tmp_path,
        home_root=tmp_path,
    )

    assert result.memory_root == tmp_path / "sase" / "memory"
    assert result.path == tmp_path / "sase" / "memory" / "foo.md"


def test_validate_memory_read_path_rejects_nested_legacy_short_path(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "short" / "foo.md", "# Foo\n")

    with pytest.raises(MemoryReadPathError, match="flat"):
        validate_memory_read_path("short/foo.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_flat_short_memory(tmp_path: Path) -> None:
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        "---\ntype: core\nparent: AGENTS.md\n---\n# Foo\n",
    )

    with pytest.raises(MemoryReadPathError, match="always-loaded"):
        validate_memory_read_path("foo.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_web_descriptor_with_strand_hint(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "glossary.md",
        "---\nweb: true\n---\n# Glossary\n",
    )

    with pytest.raises(MemoryReadPathError) as exc:
        validate_memory_read_path("glossary.md", project_root=tmp_path)

    message = str(exc.value)
    assert "always-loaded memory web descriptor" in message
    assert "sase memory read glossary:<keyword>" in message


def test_validate_memory_read_path_rejects_traversal(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note())

    with pytest.raises(MemoryReadPathError, match="traversal"):
        validate_memory_read_path("foo/../foo.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_absolute_paths(tmp_path: Path) -> None:
    target = tmp_path / "sase" / "memory" / "foo.md"
    _write(target, _long_note())

    with pytest.raises(MemoryReadPathError, match="relative"):
        validate_memory_read_path(target, project_root=tmp_path)


def test_validate_memory_read_path_rejects_missing_files(tmp_path: Path) -> None:
    with pytest.raises(MemoryReadPathError, match="does not exist"):
        validate_memory_read_path("missing.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_outside_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    link = tmp_path / "sase" / "memory" / "linked.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(MemoryReadPathError, match="outside"):
        validate_memory_read_path("linked.md", project_root=tmp_path)


def test_validate_memory_read_path_rejects_project_symlink_before_home_fallback(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    link = project / "sase" / "memory" / "linked.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    _write(home / "sase" / "memory" / "linked.md", _long_note("# Home\n"))
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(MemoryReadPathError, match="outside"):
        validate_memory_read_path(
            "linked.md",
            project_root=project,
            home_root=home,
        )


def test_validate_memory_read_path_rejects_non_markdown(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.txt", "Foo\n")

    with pytest.raises(MemoryReadPathError, match=r"\.md"):
        validate_memory_read_path("foo.txt", project_root=tmp_path)


def test_strip_leading_frontmatter_removes_only_frontmatter_block() -> None:
    text = "---\nowner: docs\n---\n# Body\n\n"

    result = strip_leading_frontmatter(text)

    assert result.stripped is True
    assert result.body == "# Body\n\n"


def test_strip_leading_frontmatter_preserves_no_frontmatter_text() -> None:
    text = "# Body\n---\nnot frontmatter\n"

    result = strip_leading_frontmatter(text)

    assert result.stripped is False
    assert result.body == text


def test_read_memory_content_tracks_byte_count_and_stripping(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note("Café\n"))
    path = validate_memory_read_path("foo.md", project_root=tmp_path)

    content = read_memory_content(path)

    assert content.body == "Café\n"
    assert content.frontmatter_stripped is True
    assert content.byte_count == len(content.raw_text.encode("utf-8"))


def test_discover_agent_identity_prefers_env_name(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    _write(artifacts_dir / "agent_meta.json", json.dumps({"name": "from-meta"}))

    identity = discover_agent_identity(
        {
            "SASE_AGENT_NAME": " from-env ",
            "SASE_AGENT": "fallback",
            "SASE_ARTIFACTS_DIR": str(artifacts_dir),
        }
    )

    assert identity == AgentIdentity(
        name="from-env",
        source="SASE_AGENT_NAME",
        artifacts_dir=str(artifacts_dir),
    )


def test_discover_agent_identity_falls_back_to_agent_meta(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    _write(artifacts_dir / "agent_meta.json", json.dumps({"name": "from-meta"}))

    identity = discover_agent_identity(
        {
            "SASE_AGENT": "1",
            "SASE_ARTIFACTS_DIR": str(artifacts_dir),
        }
    )

    assert identity == AgentIdentity(
        name="from-meta",
        source="agent_meta",
        artifacts_dir=str(artifacts_dir),
    )


def test_discover_agent_identity_ignores_agent_flag() -> None:
    assert discover_agent_identity({"SASE_AGENT": "1"}) is None


def test_require_agent_identity_raises_without_attribution() -> None:
    with pytest.raises(AgentIdentityError, match="agent attribution"):
        require_agent_identity({})


def test_append_and_read_memory_read_events_tolerates_malformed_jsonl(
    tmp_path: Path,
) -> None:
    content = _memory_content(tmp_path, "foo.md")
    event = build_memory_read_event(
        content,
        reason="Need foo",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", "/tmp/artifacts"),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-a",
    )
    log_path = tmp_path / "state" / "memory_reads.jsonl"

    append_memory_read_event(event, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(json.dumps({"schema_version": 1, "id": "missing-fields"}) + "\n")

    assert read_memory_read_events(log_path=log_path) == (event,)


def test_v1_event_upgrades_to_note_kind_defaults(tmp_path: Path) -> None:
    log_path = tmp_path / "memory_reads.jsonl"
    v1_row = {
        "schema_version": 1,
        "id": "read-legacy",
        "timestamp": "2026-05-23T12:00:00+00:00",
        "project": "proj",
        "cwd": "/tmp/demo",
        "canonical_path": "foo.md",
        "resolved_path": "/tmp/demo/memory/foo.md",
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": None,
        "reason": "Need foo",
        "byte_count": 42,
        "frontmatter_stripped": False,
    }
    log_path.write_text(json.dumps(v1_row) + "\n", encoding="utf-8")

    (event,) = read_memory_read_events(log_path=log_path)

    assert event.schema_version == 1
    assert event.canonical_path == "foo.md"
    assert event.kind == "note"
    assert event.selectors == ("foo.md",)
    assert event.resolved_targets == ("foo.md",)
    assert event.included_targets == ()
    assert event.depth is None
    assert event.scope_origin == ()


def test_batch_event_round_trips_through_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "memory_reads.jsonl"
    event = build_memory_read_batch_event(
        kind="strand",
        selectors=["glossary:stitch"],
        resolved_targets=["glossary:stitch"],
        included_targets=["glossary:patch"],
        depth=None,
        scope_origin={"glossary:stitch": "project", "glossary:patch": "project"},
        byte_count=64,
        frontmatter_stripped=False,
        reason="Need stitch",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-batch",
    )

    append_memory_read_event(event, log_path=log_path)

    assert read_memory_read_events(log_path=log_path) == (event,)
    assert event.schema_version == 2
    assert event.canonical_path == "glossary:stitch"
    assert event.resolved_path == ""


def test_filter_memory_read_events_matches_resolved_targets() -> None:
    strand_event = build_memory_read_batch_event(
        kind="strand",
        selectors=["glossary:stitch"],
        resolved_targets=["glossary:stitch"],
        byte_count=10,
        frontmatter_stripped=False,
        reason="Need stitch",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=Path("/tmp/demo"),
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-strand",
    )

    assert filter_memory_read_events(
        [strand_event], canonical_path="glossary:stitch"
    ) == (strand_event,)


def test_memory_read_log_path_uses_project_state_under_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert memory_read_log_path("proj") == (
        tmp_path / ".sase" / "projects" / "proj" / "memory_reads.jsonl"
    )


def test_memory_read_log_path_canonicalizes_project_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )

    assert memory_read_log_path("bob") == (
        tmp_path / ".sase" / "projects" / "bob-cli" / "memory_reads.jsonl"
    )


def test_memory_read_aggregation_groups_by_path_and_agent(tmp_path: Path) -> None:
    content = _memory_content(tmp_path, "foo.md")
    base = build_memory_read_event(
        content,
        reason="First",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-a",
    )
    second = replace(
        base,
        id="read-b",
        timestamp="2026-05-23T12:01:00+00:00",
        agent_name="agent-b",
        reason="Second",
    )
    other = replace(
        base,
        id="read-c",
        timestamp="2026-05-23T12:02:00+00:00",
        canonical_path="bar.md",
        agent_name="agent-a",
        reason="Third",
    )

    path_summaries = summarize_memory_reads_by_path([base, second, other])
    agent_summaries = summarize_memory_reads_by_agent([base, second, other])

    assert path_summaries[0].canonical_path == "bar.md"
    assert path_summaries[0].read_count == 1
    assert path_summaries[1].canonical_path == "foo.md"
    assert path_summaries[1].read_count == 2
    assert path_summaries[1].distinct_agent_count == 2
    assert path_summaries[1].last_agent == "agent-b"
    assert path_summaries[1].last_reason == "Second"
    assert agent_summaries[0].agent_name == "agent-a"
    assert agent_summaries[0].read_count == 2
    assert agent_summaries[0].distinct_path_count == 2
    assert agent_summaries[1].agent_name == "agent-b"
    assert filter_memory_read_events(
        [base, second, other],
        canonical_path="foo.md",
        agent_name="agent-b",
    ) == (second,)


def _memory_content(tmp_path: Path, relative_path: str):
    _write(tmp_path / "sase" / "memory" / relative_path, _long_note("# Body\n"))
    path = validate_memory_read_path(relative_path, project_root=tmp_path)
    return read_memory_content(path)
