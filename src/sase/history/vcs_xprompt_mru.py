"""MRU tracking for VCS xprompt workflow prefixes."""

import json
from pathlib import Path

_MRU_FILE = Path.home() / ".sase" / "vcs_xprompt_mru.json"
_MAX_ENTRIES = 10


def load_vcs_xprompt_mru() -> list[str]:
    """Load the MRU list from disk.

    Returns:
        Ordered list of VCS prefix strings, most recently used first.
    """
    if not _MRU_FILE.exists():
        return []
    try:
        with open(_MRU_FILE, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return [e for e in entries if isinstance(e, str)][:_MAX_ENTRIES]
    except (OSError, json.JSONDecodeError):
        return []


def record_vcs_xprompt_usage(prefix: str) -> None:
    """Move/add prefix to the front of the MRU list, cap at 10, save to disk.

    Args:
        prefix: VCS workflow prefix string (e.g. ``"#gh:sase"``).
    """
    entries = load_vcs_xprompt_mru()
    entries = [e for e in entries if e != prefix]
    entries.insert(0, prefix)
    entries = entries[:_MAX_ENTRIES]
    try:
        _MRU_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_MRU_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, indent=2)
    except OSError:
        pass
