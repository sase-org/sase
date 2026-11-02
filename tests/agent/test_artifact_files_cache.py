"""Tests for the Phase-6 artifact file cache and tail cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from sase.agent.artifact_files_cache import _ArtifactFileCache, _TailCache
from sase.legacy_xprompt_names import LEGACY_RAW_XPROMPT_FILENAME


def test_read_text_caches_by_signature(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
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
    cache = _ArtifactFileCache()
    f = tmp_path / "prompt.md"
    f.write_text("hello", encoding="utf-8")
    assert cache.read_text(str(f)) == "hello"

    f.write_text("world!!", encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000))
    assert cache.read_text(str(f)) == "world!!"


def test_read_text_uses_module_owned_open_hook(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
    f = tmp_path / "prompt.md"
    f.write_text("hello", encoding="utf-8")
    open_text = Mock(return_value="hooked")

    with patch("sase.agent.artifact_files_cache._open_text", open_text):
        assert cache.read_text(str(f)) == "hooked"
        assert cache.read_text(str(f)) == "hooked"

    open_text.assert_called_once_with(str(f))


def test_read_json_caches(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
    f = tmp_path / "agent_meta.json"
    f.write_text(json.dumps({"chat_path": "~/chat.md"}), encoding="utf-8")

    first = cache.read_json(str(f))
    second = cache.read_json(str(f))
    assert first == second == {"chat_path": "~/chat.md"}


def test_select_prompt_file_caches_glob(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
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

    import sase.agent.artifact_files_cache as mod

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
    cache = _ArtifactFileCache()
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


def test_select_prompt_file_skips_commit_finalizer_followups(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
    d = tmp_path / "artifacts"
    d.mkdir()
    original = d / "sase_prompt.md"
    original.write_text(
        "Previous Conversation\n---\n# New Query\ndo it", encoding="utf-8"
    )
    finalizer = d / "commit_finalizer_pass_1_prompt.md"
    finalizer.write_text("follow up", encoding="utf-8")
    # Make the finalizer prompt the newest so it would win without the filter.
    st = original.stat()
    os.utime(
        finalizer,
        ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000),
    )

    selected = cache.select_prompt_file(str(d), is_workflow_child=False, step_name=None)
    assert selected == str(original)


def test_select_prompt_file_excludes_raw_across_mtimes(tmp_path: Path) -> None:
    for raw_delta, expanded_delta in [
        (5_000_000_000, 0),
        (0, 0),
        (0, 5_000_000_000),
    ]:
        cache = _ArtifactFileCache()
        d = tmp_path / f"artifacts-{raw_delta}-{expanded_delta}"
        d.mkdir()
        raw = d / "raw_prompt.md"
        expanded = d / "01_prompt.md"
        raw.write_text("RAW", encoding="utf-8")
        expanded.write_text("EXPANDED", encoding="utf-8")
        base = raw.stat().st_mtime_ns
        os.utime(raw, ns=(base + raw_delta, base + raw_delta))
        os.utime(expanded, ns=(base + expanded_delta, base + expanded_delta))
        selected = cache.select_prompt_file(
            str(d), is_workflow_child=False, step_name=None
        )
        assert selected == str(expanded)


def test_select_prompt_file_excludes_legacy_raw(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
    d = tmp_path / "artifacts"
    d.mkdir()
    raw = d / LEGACY_RAW_XPROMPT_FILENAME
    expanded = d / "01_prompt.md"
    raw.write_text("RAW", encoding="utf-8")
    expanded.write_text("EXPANDED", encoding="utf-8")
    st = expanded.stat()
    os.utime(raw, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000))
    assert cache.select_prompt_file(
        str(d), is_workflow_child=False, step_name=None
    ) == str(expanded)


def test_select_prompt_file_tie_prefers_greatest_path_both_orders(
    tmp_path: Path,
) -> None:
    import sase.agent.artifact_files_cache as mod

    d = tmp_path / "artifacts"
    d.mkdir()
    first = d / "01_prompt.md"
    second = d / "02_prompt.md"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    base = first.stat().st_mtime_ns
    os.utime(first, ns=(base, base))
    os.utime(second, ns=(base, base))
    real_listdir = os.listdir
    for order in (["01_prompt.md", "02_prompt.md"], ["02_prompt.md", "01_prompt.md"]):
        cache = _ArtifactFileCache()
        mod.os.listdir = lambda path, _o=order, _d=str(d): (  # type: ignore[assignment]
            list(_o) if path == _d else real_listdir(path)
        )
        try:
            selected = cache.select_prompt_file(
                str(d), is_workflow_child=False, step_name=None
            )
        finally:
            mod.os.listdir = real_listdir  # type: ignore[assignment]
        assert selected == str(second)


def test_select_prompt_file_raw_only_and_empty_are_none(tmp_path: Path) -> None:
    raw_only = tmp_path / "raw-only"
    raw_only.mkdir()
    (raw_only / "raw_prompt.md").write_text("RAW", encoding="utf-8")
    cache = _ArtifactFileCache()
    assert (
        cache.select_prompt_file(str(raw_only), is_workflow_child=False, step_name=None)
        is None
    )
    # A repeat call hits the cached empty selection.
    assert (
        cache.select_prompt_file(str(raw_only), is_workflow_child=False, step_name=None)
        is None
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        cache.select_prompt_file(str(empty), is_workflow_child=False, step_name=None)
        is None
    )


def test_select_prompt_file_workflow_fallback_to_other_prompts(
    tmp_path: Path,
) -> None:
    cache = _ArtifactFileCache()
    d = tmp_path / "artifacts"
    d.mkdir()
    other = d / "01-other_prompt.md"
    fallback = d / "02-else_prompt.md"
    other.write_text("a", encoding="utf-8")
    fallback.write_text("b", encoding="utf-8")
    st = fallback.stat()
    os.utime(other, ns=(st.st_mtime_ns + 1_000_000_000, st.st_mtime_ns + 1_000_000_000))
    assert cache.select_prompt_file(
        str(d), is_workflow_child=True, step_name="coder"
    ) == str(other)


def test_select_prompt_file_invalidates_on_add_remove_and_mtime(
    tmp_path: Path,
) -> None:
    cache = _ArtifactFileCache()
    d = tmp_path / "artifacts"
    d.mkdir()
    first = d / "01_prompt.md"
    first.write_text("a", encoding="utf-8")
    assert cache.select_prompt_file(
        str(d), is_workflow_child=False, step_name=None
    ) == str(first)
    second = d / "02_prompt.md"
    second.write_text("b", encoding="utf-8")
    st = first.stat()
    os.utime(
        second, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000)
    )
    assert cache.select_prompt_file(
        str(d), is_workflow_child=False, step_name=None
    ) == str(second)
    second.unlink()
    assert cache.select_prompt_file(
        str(d), is_workflow_child=False, step_name=None
    ) == str(first)
    first.write_text("a-changed", encoding="utf-8")
    st = first.stat()
    os.utime(first, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000))
    assert cache.select_prompt_file(
        str(d), is_workflow_child=False, step_name=None
    ) == str(first)


def test_read_reply_chunks_decodes_jointly(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
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

    tail = _TailCache(path=str(f))
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
    tail = _TailCache(path=str(f))
    assert tail.read() == "abcdef"

    f.write_text("xyz", encoding="utf-8")
    assert tail.read() == "xyz"
    assert tail.size == 3
    assert tail.offset == 3


def test_tail_cache_resets_when_monitor_log_rotates(tmp_path: Path) -> None:
    f = tmp_path / "live_reply.md"
    f.write_text("old current with more bytes\n", encoding="utf-8")
    tail = _TailCache(path=str(f))
    assert tail.read() == "old current with more bytes\n"

    os.replace(f, f.with_name("live_reply.md.1"))
    f.write_text("new current\n", encoding="utf-8")

    assert tail.read() == "new current\n"
    assert tail.size == len("new current\n")
    assert tail.offset == len("new current\n")


def test_read_live_reply_uses_tail_cache(tmp_path: Path) -> None:
    cache = _ArtifactFileCache()
    f = tmp_path / "live_reply.md"
    f.write_text("hello", encoding="utf-8")
    assert cache.read_live_reply(str(f)) == "hello"

    tail = cache.tail_cache_for(str(f))
    assert tail.size == 5
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(" world")
    assert cache.read_live_reply(str(f)) == "hello world"
    assert tail.size == 11
