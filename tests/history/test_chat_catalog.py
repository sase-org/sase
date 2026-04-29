"""Tests for the chat_catalog foundation helpers."""

import json
import os
from pathlib import Path

import pytest
from sase.history.chat_catalog import (
    ChatRefError,
    ChatTranscriptInfo,
    chat_info_to_json,
    list_chat_transcripts,
    resolve_chat_ref,
)

from tests.conftest import redirect_sase_home


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _setup_fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Anchor Path.home() at tmp_path and redirect ~/.sase to tmp_path/.sase.

    Returns the ``~/.sase`` directory so callers can set up artifacts there.
    """
    sase_home = tmp_path / ".sase"
    sase_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    redirect_sase_home(monkeypatch, sase_home)
    return sase_home


def _write_chat(
    sase_home: Path,
    basename: str,
    *,
    workflow: str = "run",
    agent: str | None = None,
    prompt: str = "Hello",
    response: str = "World",
    shard: str | None = "202604",
) -> Path:
    """Create a chat file with the standard header layout."""
    if shard is None:
        chat_dir = sase_home / "chats"
    else:
        chat_dir = sase_home / "chats" / shard
    chat_dir.mkdir(parents=True, exist_ok=True)
    fname = basename if basename.endswith(".md") else f"{basename}.md"
    path = chat_dir / fname
    header = f"# Chat History - {workflow}"
    if agent:
        header += f" ({agent})"
    body = (
        f"{header}\n\n"
        f"**Timestamp:** 2026-04-29 10:15:08 EDT\n\n"
        f"## Prompt\n\n{prompt}\n\n"
        f"## Response\n\n{response}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def _write_named_agent(
    sase_home: Path,
    *,
    project: str = "sase",
    artifact_ts: str = "260429_101500",
    name: str = "alpha",
    done: dict | None,
    meta: dict | None = None,
) -> Path:
    """Create a project artifact directory for a named agent."""
    artifact_dir = (
        sase_home / "projects" / project / "artifacts" / "ace-run" / artifact_ts
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    meta_full: dict[str, object] = {"name": name}
    if meta:
        meta_full.update(meta)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(meta_full), encoding="utf-8"
    )
    if done is not None:
        (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return artifact_dir


# ---------------------------------------------------------------------------
# list_chat_transcripts
# ---------------------------------------------------------------------------


def test_list_finds_sharded_and_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    sharded = _write_chat(home, "branch-run-260429_101500", shard="202604")
    legacy = _write_chat(home, "old-run-251128_120000", shard=None)

    infos = list_chat_transcripts()
    paths = {info.absolute_path for info in infos}
    assert str(sharded) in paths
    assert str(legacy) in paths


def test_list_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    older = _write_chat(home, "branch-run-260101_010000")
    newer = _write_chat(home, "branch-run-260429_101500")
    # Force ordering by mtime regardless of filename timestamps.
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    infos = list_chat_transcripts()
    assert infos[0].absolute_path == str(newer)
    assert infos[1].absolute_path == str(older)


def test_list_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    for i in range(5):
        _write_chat(home, f"branch-run-26042{i}_101500")
    infos = list_chat_transcripts(limit=2)
    assert len(infos) == 2


def test_list_query_matches_path_or_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(home, "alpha-run-260429_101500", prompt="hello world")
    _write_chat(home, "beta-run-260429_101501", prompt="quick brown fox")
    _write_chat(home, "gamma-run-260429_101502", prompt="completely unrelated")

    by_path = list_chat_transcripts(query="alpha")
    assert [i.basename for i in by_path] == ["alpha-run-260429_101500"]

    by_content = list_chat_transcripts(query="brown fox")
    assert [i.basename for i in by_content] == ["beta-run-260429_101501"]


def test_list_populates_snippets_and_header_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(
        home,
        "branch-run-planner-260429_101500",
        workflow="run",
        agent="planner",
        prompt="Can you help me?",
        response="Implemented the foo.",
    )
    [info] = list_chat_transcripts()
    assert info.workflow == "run"
    assert info.agent == "planner"
    assert info.timestamp == "260429_101500"
    assert info.prompt_snippet == "Can you help me?"
    assert info.response_snippet == "Implemented the foo."


def test_list_tolerates_malformed_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    bad_dir = home / "chats" / "202604"
    bad_dir.mkdir(parents=True, exist_ok=True)
    bad = bad_dir / "garbled-260429_101500.md"
    bad.write_bytes(b"\xff\xfe not really markdown")
    _write_chat(home, "good-run-260429_101501")

    infos = list_chat_transcripts()
    basenames = {i.basename for i in infos}
    assert "garbled-260429_101500" in basenames
    assert "good-run-260429_101501" in basenames
    garbled = next(i for i in infos if i.basename == "garbled-260429_101500")
    # Header parsing fails gracefully — workflow/agent are None.
    assert garbled.workflow is None
    assert garbled.agent is None


def test_list_handles_giant_transcript_without_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    big_dir = home / "chats" / "202604"
    big_dir.mkdir(parents=True, exist_ok=True)
    big = big_dir / "huge-run-260429_101500.md"
    head = (
        "# Chat History - run\n\n"
        "**Timestamp:** 2026-04-29 10:15:08 EDT\n\n"
        "## Prompt\n\nshort prompt\n\n"
        "## Response\n\nshort response\n\n"
        "## Trailer\n\n"
    )
    # ~2 MB tail to confirm we don't read it all.
    big.write_text(head + ("x" * (2 * 1024 * 1024)), encoding="utf-8")

    [info] = list_chat_transcripts()
    assert info.prompt_snippet == "short prompt"
    assert info.response_snippet == "short response"
    assert info.size_bytes > 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# chat_info_to_json
# ---------------------------------------------------------------------------


def test_chat_info_to_json_stable_key_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(home, "branch-run-260429_101500")
    [info] = list_chat_transcripts()
    payload = chat_info_to_json(info)
    assert list(payload.keys()) == [
        "path",
        "basename",
        "mtime",
        "size_bytes",
        "workflow",
        "agent",
        "timestamp",
        "prompt_snippet",
        "response_snippet",
    ]
    # Round-trips through json without losing key order.
    text = json.dumps(payload)
    assert json.loads(text) == payload


# ---------------------------------------------------------------------------
# resolve_chat_ref
# ---------------------------------------------------------------------------


def test_resolve_requires_exactly_one_selector() -> None:
    with pytest.raises(ChatRefError):
        resolve_chat_ref()
    with pytest.raises(ChatRefError):
        resolve_chat_ref(agent="a", path="/tmp/x.md")


def test_resolve_path_expands_home_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-260429_101500")
    assert resolve_chat_ref(path=str(chat)) == str(chat)
    # ~-prefixed form expands.
    rel = "~/.sase/chats/202604/branch-run-260429_101500.md"
    assert resolve_chat_ref(path=rel) == str(chat)
    with pytest.raises(FileNotFoundError):
        resolve_chat_ref(path=str(tmp_path / "nope.md"))


def test_resolve_basename_uses_sharded_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-260429_101500")
    # Bare basename without extension.
    assert resolve_chat_ref(basename="branch-run-260429_101500") == str(chat)
    # Basename with extension.
    assert resolve_chat_ref(basename="branch-run-260429_101500.md") == str(chat)
    with pytest.raises(FileNotFoundError):
        resolve_chat_ref(basename="missing-260429_101500")


def test_resolve_agent_via_done_response_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-alpha-260429_101500")
    _write_named_agent(
        home,
        artifact_ts="260429_101500",
        name="alpha",
        done={"response_path": str(chat), "outcome": "completed"},
    )
    assert resolve_chat_ref(agent="alpha") == str(chat)


def test_resolve_agent_falls_back_to_meta_chat_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-bravo-260429_101500")
    # In-progress agent: no done.json, but a live pid so find_named_agent
    # returns it, and chat_path on agent_meta.json is the resume target.
    _write_named_agent(
        home,
        artifact_ts="260429_101500",
        name="bravo",
        done=None,
        meta={"chat_path": str(chat), "pid": os.getpid()},
    )
    assert resolve_chat_ref(agent="bravo") == str(chat)


def test_resolve_agent_unknown_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_chat_ref(agent="ghost")


# ---------------------------------------------------------------------------
# dataclass surface
# ---------------------------------------------------------------------------


def test_shorten_home_replaces_home_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.history import chat_catalog

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    nested = str(fake_home / ".sase" / "chats" / "x.md")
    assert chat_catalog._shorten_home(nested) == "~/.sase/chats/x.md"
    assert chat_catalog._shorten_home("/tmp/elsewhere.md") == "/tmp/elsewhere.md"


def test_dataclass_is_frozen() -> None:
    info = ChatTranscriptInfo(
        path="~/chats/x.md",
        absolute_path="/tmp/x.md",
        basename="x",
        mtime="2026-04-29T10:15:08-04:00",
        size_bytes=1,
        workflow=None,
        agent=None,
        timestamp=None,
        prompt_snippet=None,
        response_snippet=None,
    )
    with pytest.raises(AttributeError):
        info.basename = "y"  # type: ignore[misc]
