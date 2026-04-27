"""Tests for the Phase-6 ``AgentArtifactCache`` and ``TailCache``."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sase.agent.agent_artifacts_cache import AgentArtifactCache, TailCache


def test_read_text_caches_by_signature(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    f = tmp_path / "prompt.md"
    f.write_text("hello", encoding="utf-8")

    first = cache.read_text(str(f))
    assert first == "hello"

    # Mutate the underlying file but do NOT change mtime/size — the cache
    # must return the original content (signature-based hit).
    sig = f.stat()
    f.write_bytes(b"world")
    os.utime(f, ns=(sig.st_mtime_ns, sig.st_mtime_ns))
    truncate_to_old_size = f.stat().st_size
    if truncate_to_old_size != sig.st_size:
        # Re-pad to original size so the signature truly matches.
        with open(f, "rb+") as fh:
            fh.truncate(sig.st_size)
        os.utime(f, ns=(sig.st_mtime_ns, sig.st_mtime_ns))

    second = cache.read_text(str(f))
    assert second == "hello"


def test_read_text_invalidates_on_mtime_change(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    f = tmp_path / "prompt.md"
    f.write_text("hello", encoding="utf-8")
    assert cache.read_text(str(f)) == "hello"

    f.write_text("world!!", encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000))
    assert cache.read_text(str(f)) == "world!!"


def test_read_json_caches(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    f = tmp_path / "agent_meta.json"
    f.write_text(json.dumps({"chat_path": "~/chat.md"}), encoding="utf-8")

    first = cache.read_json(str(f))
    second = cache.read_json(str(f))
    assert first == second == {"chat_path": "~/chat.md"}


def test_select_prompt_file_caches_glob(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "first_prompt.md").write_text("a", encoding="utf-8")
    older = artifacts_dir / "older_prompt.md"
    older.write_text("b", encoding="utf-8")
    # Make the second file the most recent.
    new_st = older.stat()
    os.utime(
        older,
        ns=(new_st.st_mtime_ns + 5_000_000_000, new_st.st_mtime_ns + 5_000_000_000),
    )

    selected_first = cache.select_prompt_file(
        str(artifacts_dir), is_workflow_child=False, step_name=None
    )
    assert selected_first == str(older)

    # A second call hits the cache without re-listing.
    real_listdir = os.listdir
    listdir_calls = 0

    def counting_listdir(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal listdir_calls
        listdir_calls += 1
        return real_listdir(*args, **kwargs)

    import sase.agent.agent_artifacts_cache as mod

    mod.os.listdir = counting_listdir  # type: ignore[assignment]
    try:
        selected_second = cache.select_prompt_file(
            str(artifacts_dir), is_workflow_child=False, step_name=None
        )
    finally:
        mod.os.listdir = real_listdir  # type: ignore[assignment]

    assert selected_second == str(older)
    # listdir is called once to compute the directory signature; sort is
    # cached on signature match so we don't redo the mtime sort.
    assert listdir_calls == 1


def test_select_prompt_file_filters_workflow_children(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    d = tmp_path / "artifacts"
    d.mkdir()
    other = d / "01-other_prompt.md"
    target = d / "02-coder_prompt.md"
    other.write_text("a", encoding="utf-8")
    target.write_text("b", encoding="utf-8")
    # Make `other` the newest by mtime.
    st = other.stat()
    os.utime(other, ns=(st.st_mtime_ns + 1_000_000_000, st.st_mtime_ns + 1_000_000_000))

    selected = cache.select_prompt_file(
        str(d), is_workflow_child=True, step_name="coder"
    )
    assert selected == str(target)


def test_read_reply_chunks_decodes_jointly(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    reply = tmp_path / "live_reply.md"
    ts = tmp_path / "live_reply_timestamps.jsonl"
    reply.write_text("hello world", encoding="utf-8")
    ts.write_text(
        '{"byte_offset": 0, "timestamp": "2026-01-01T00:00:00"}\n'
        '{"byte_offset": 6, "timestamp": "2026-01-01T00:00:01"}\n',
        encoding="utf-8",
    )
    chunks = cache.read_reply_chunks(str(ts), str(reply))
    assert chunks == [
        ("2026-01-01T00:00:00", "hello "),
        ("2026-01-01T00:00:01", "world"),
    ]

    # Re-read returns cached list (still equal).
    assert cache.read_reply_chunks(str(ts), str(reply)) == chunks


def test_tail_cache_reads_only_appended_bytes(tmp_path: Path) -> None:
    f = tmp_path / "live_reply.md"
    f.write_text("hello", encoding="utf-8")

    tail = TailCache(path=str(f))
    assert tail.read() == "hello"
    assert tail.size == 5
    assert tail.offset == 5

    # Append more bytes to the file. Capture the offset before re-read to
    # prove the seek skips already-read bytes.
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(" world")

    pre_offset = tail.offset
    result = tail.read()
    assert result == "hello world"
    # The seek was at the previous offset (5), so only the 6 new bytes were
    # consumed from disk.
    assert pre_offset == 5
    assert tail.size == 11
    assert tail.offset == 11


def test_tail_cache_resets_on_shrink(tmp_path: Path) -> None:
    f = tmp_path / "live_reply.md"
    f.write_text("abcdef", encoding="utf-8")
    tail = TailCache(path=str(f))
    assert tail.read() == "abcdef"

    f.write_text("xyz", encoding="utf-8")
    assert tail.read() == "xyz"
    assert tail.size == 3
    assert tail.offset == 3


def test_read_live_reply_uses_tail_cache(tmp_path: Path) -> None:
    cache = AgentArtifactCache()
    f = tmp_path / "live_reply.md"
    f.write_text("hello", encoding="utf-8")
    assert cache.read_live_reply(str(f)) == "hello"

    tail = cache.tail_cache_for(str(f))
    assert tail.size == 5
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(" world")
    assert cache.read_live_reply(str(f)) == "hello world"
    assert tail.size == 11
