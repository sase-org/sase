"""Legacy prompt-history migration."""

from __future__ import annotations

from pathlib import Path

from sase.history import prompt_store as store


def _legacy_backup_path() -> Path:
    timestamp = store.generate_timestamp()
    return store.prompt_history_dir() / f"legacy-imported-{timestamp}.json.bak"


def _raw_prompt_count(path: Path) -> int:
    with open(path, encoding="utf-8") as file:
        data = store.json.load(file)
    if not isinstance(data, dict):
        raise store.PromptHistoryLoadError
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        raise store.PromptHistoryLoadError
    return len(prompts)


def ensure_migrated() -> None:
    """Migrate the legacy single-file store into shards once, losslessly."""
    history_dir = store.prompt_history_dir()
    if history_dir.exists() and history_dir.is_dir():
        return

    legacy_file = store.legacy_prompt_history_file()
    if not legacy_file.exists():
        return

    entries = store.load_legacy_prompt_history_for_write()
    buckets: dict[str, list[store.PromptEntry]] = {}
    for entry in entries:
        key = store.shard_key_for_timestamp(entry.last_used)
        buckets.setdefault(key, []).append(entry)

    history_dir.mkdir(parents=True, exist_ok=True)
    written_count = 0
    try:
        for key, shard_entries in buckets.items():
            shard_entries.sort(key=lambda entry: entry.last_used, reverse=True)
            if not store.save_shard(store.shard_path(key), shard_entries):
                raise store.PromptHistoryLoadError
            written_count += len(shard_entries)
        if written_count != len(entries):
            raise store.PromptHistoryLoadError
        raw_count = _raw_prompt_count(legacy_file)
        if written_count != raw_count:
            raise store.PromptHistoryLoadError
        store.os.replace(legacy_file, _legacy_backup_path())
    except Exception:
        for path in store.iter_shard_paths_newest_first():
            try:
                path.unlink()
            except OSError:
                pass
        try:
            history_dir.rmdir()
        except OSError:
            pass
        raise


def ensure_migrated_for_read() -> None:
    """Ensure migration before a read, taking the global lock only if needed."""
    history_dir = store.prompt_history_dir()
    legacy_file = store.legacy_prompt_history_file()
    if history_dir.exists() or not legacy_file.exists():
        return
    with store.locked_prompt_history():
        ensure_migrated()
