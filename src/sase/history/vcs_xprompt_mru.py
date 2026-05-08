"""MRU tracking for VCS xprompt workflow prefixes."""

import json
from pathlib import Path

_MRU_FILE = Path("~/.sase/vcs_xprompt_mru.json")
_MAX_ENTRIES = 100


def _mru_file() -> Path:
    return Path(_MRU_FILE).expanduser()


def load_vcs_xprompt_mru() -> list[str]:
    """Load the MRU list from disk.

    Returns:
        Ordered list of VCS prefix strings, most recently used first.
    """
    mru_file = _mru_file()
    if not mru_file.exists():
        return []
    try:
        with open(mru_file, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return [e for e in entries if isinstance(e, str)][:_MAX_ENTRIES]
    except (OSError, json.JSONDecodeError):
        return []


def load_launchable_vcs_xprompt_mru(
    projects_dir: Path | None = None,
    *,
    prune: bool = True,
) -> list[str]:
    """Load MRU prefixes, dropping stale entries for known non-launchable projects."""
    entries = load_vcs_xprompt_mru()
    filtered = [
        entry
        for entry in entries
        if not _is_stale_known_project_prefix(entry, projects_dir)
    ]
    if prune and filtered != entries:
        _save_vcs_xprompt_mru(filtered)
    return filtered


def record_vcs_xprompt_usage(prefix: str) -> None:
    """Move/add prefix to the front of the MRU list, cap at 100, save to disk.

    Args:
        prefix: VCS workflow prefix string (e.g. ``"#gh:sase"``).
    """
    entries = load_vcs_xprompt_mru()
    if _is_stale_known_project_prefix(prefix):
        filtered = [e for e in entries if e != prefix]
        if filtered != entries:
            _save_vcs_xprompt_mru(filtered)
        return

    entries = [e for e in entries if e != prefix]
    entries.insert(0, prefix)
    entries = entries[:_MAX_ENTRIES]
    _save_vcs_xprompt_mru(entries)


def _save_vcs_xprompt_mru(entries: list[str]) -> None:
    try:
        mru_file = _mru_file()
        mru_file.parent.mkdir(parents=True, exist_ok=True)
        with open(mru_file, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, indent=2)
    except OSError:
        pass


def _is_stale_known_project_prefix(
    prefix: str,
    projects_dir: Path | None = None,
) -> bool:
    project_name = _project_name_from_vcs_prefix(prefix)
    if project_name is None:
        return False

    projects_base = projects_dir or Path("~/.sase/projects").expanduser()
    project_file = projects_base / project_name / f"{project_name}.gp"
    if not project_file.is_file():
        return False

    from sase.ace.tui.modals.project_discovery import is_launchable_project

    return not is_launchable_project(project_name, projects_base)


def _project_name_from_vcs_prefix(prefix: str) -> str | None:
    from sase.xprompt._parsing import extract_project_from_vcs_tag

    return extract_project_from_vcs_tag(prefix)
