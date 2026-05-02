---
create_time: 2026-04-27 09:34:24
status: done
prompt: sdd/prompts/202604/persist_agents_grouping_mode.md
---
# Persist the Agents-tab grouping mode across TUI restarts

## Problem

The Agents tab supports three grouping modes — `STANDARD`, `BY_DATE`, `BY_STATUS` — cycled via the `o` key (recently
rebound from `g`; commit `31c10fc3`). Today the mode is initialized to `STANDARD` on every TUI launch
(`src/sase/ace/tui/actions/startup.py:221`), so a user who prefers `BY_STATUS` has to press `o` twice every time they
relaunch `sase ace`.

We want the TUI to remember the last-used mode and restore it on next launch.

## Investigation

### Where the mode lives today

- **Initialization**: `src/sase/ace/tui/actions/startup.py:219-227` — `_init_app_state` (`StartupMixin`) hard-codes
  `_grouping_mode = GroupingMode.STANDARD` and seeds `_group_fold_registries` with a single registry for STANDARD.
- **Type**: `src/sase/ace/tui/models/agent_groups.py:62-80` — `GroupingMode` is a `str`-valued `Enum`
  (`STANDARD = "standard"`, `BY_DATE = "by_date"`, `BY_STATUS = "by_status"`). Round-tripping through the string value
  is straightforward.
- **Mutation**: `src/sase/ace/tui/actions/agents/_grouping.py:65-88` — `action_cycle_grouping_mode` is the only place
  the mode changes after init.
- **Type declarations on the mixin**: also referenced in `src/sase/ace/tui/actions/agents/_core.py:39-41`.

### Existing persistence precedents (`~/.sase/` is for state, `~/.config/sase/` is for config)

The codebase has two clean, single-value/single-file precedents the explore agent surfaced:

- `src/sase/ace/last_selection.py` — 27 lines. Stores a single string (last ChangeSpec name) at
  `~/.sase/last_selection.txt`. Two functions: `load_last_selection()` and `save_last_selection()`. Load returns `None`
  on missing/unreadable file; save returns `bool`.
- `src/sase/ace/dismissed_agents.py` — JSON-backed at `~/.sase/dismissed_agents.json`. Loaded once at startup
  (`startup.py:245`).

Both files are global (not per-project) and live under `~/.sase/`. Save-on-quit happens in
`src/sase/ace/tui/actions/lifecycle.py:149-151` (`_do_quit`), via `_save_current_selection()`.

### Project-scoped vs global

The Agents tab is **global** — it loads agents across all projects via `load_agents_from_disk()` and the app has no
"current project" concept. Persisting grouping mode globally (one value, not per-project) matches the data model.

### Test surface

`tests/ace/tui/test_agent_grouping_cycle.py` exercises `action_cycle_grouping_mode()` directly with a fixture app whose
`_grouping_mode` is set in the test's `MagicMock`/setup — it does not go through `_init_app_state`, so existing tests
are unaffected by changing the init path. New tests are needed for the load/save logic itself.

## Plan

### Step 1 — New module `src/sase/ace/grouping_mode_state.py`

Mirror `last_selection.py` exactly. ~25 lines:

```python
"""Storage for the last-used Agents-tab grouping mode."""

from pathlib import Path

from .tui.models.agent_groups import GroupingMode

_GROUPING_MODE_FILE = Path.home() / ".sase" / "grouping_mode.txt"
_DEFAULT = GroupingMode.STANDARD


def load_grouping_mode() -> GroupingMode:
    """Load the persisted grouping mode, or STANDARD if missing/corrupt."""
    if not _GROUPING_MODE_FILE.exists():
        return _DEFAULT
    try:
        raw = _GROUPING_MODE_FILE.read_text().strip()
    except OSError:
        return _DEFAULT
    try:
        return GroupingMode(raw)  # value-based lookup ("standard", "by_date", ...)
    except ValueError:
        return _DEFAULT


def save_grouping_mode(mode: GroupingMode) -> bool:
    """Persist *mode* to disk. Returns True on success."""
    try:
        _GROUPING_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GROUPING_MODE_FILE.write_text(mode.value)
        return True
    except OSError:
        return False
```

Why a separate file rather than rolling into a multi-key `ui_state.json`: the codebase's established pattern is
one-value-per-file (`last_selection.txt`, `dismissed_agents.json`). Inventing a new aggregated state file would create
two parallel conventions. We can revisit if a third or fourth piece of UI state appears and the proliferation starts to
feel clumsy — until then, follow the precedent.

Why store the `.value` (not `.name`): the enum is `str`-valued, and `GroupingMode(raw)` is the natural constructor.
Future renames of enum _member names_ won't break stored values.

### Step 2 — Load on startup

Edit `src/sase/ace/tui/actions/startup.py` around lines 218-227:

```python
from ...grouping_mode_state import load_grouping_mode
# ...
self._grouping_mode: GroupingMode = load_grouping_mode()
self._group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry] = {
    self._grouping_mode: AgentGroupFoldRegistry(),
}
self._group_fold_registry: AgentGroupFoldRegistry = self._group_fold_registries[
    self._grouping_mode
]
```

Note the registry seed now keys off the loaded mode (rather than always seeding the STANDARD slot). The cycle action
already lazy-allocates other modes via `_ensure_mode_registry`, so this is just consistent with that.

### Step 3 — Save on cycle

Edit `src/sase/ace/tui/actions/agents/_grouping.py:action_cycle_grouping_mode`. After `self._grouping_mode = next_mode`
(line 73), persist immediately:

```python
from ...grouping_mode_state import save_grouping_mode
save_grouping_mode(next_mode)
```

**Save-on-cycle vs. save-on-quit — chosen rationale:**

- Cycles are rare (a few presses per session, max). The write cost is negligible.
- Save-on-cycle is robust to the TUI crashing or being killed (`SIGKILL`, OOM) without going through `_do_quit`.
- `last_selection.txt` saves only on quit because the value changes on every navigation keystroke — that argument
  doesn't apply here.
- It also keeps the persistence concern co-located with the only mutation site, rather than smearing it into the quit
  path.

We will _not_ add a `_do_quit` hook for grouping mode. (If, during review, the user prefers save-on-quit anyway,
swapping is trivial: drop the call in `_grouping.py`, add `save_grouping_mode(self._grouping_mode)` to
`_save_current_selection` or `_do_quit` in `lifecycle.py:149`.)

### Step 4 — Tests

Add `tests/ace/test_grouping_mode_state.py` (new file, alongside other `tests/ace/test_*.py` like
`test_dismissed_agents.py` if it exists, otherwise `tests/ace/`). Cover:

1. `load_grouping_mode()` returns `STANDARD` when the file is absent.
2. Round-trip: `save_grouping_mode(GroupingMode.BY_STATUS)` then `load_grouping_mode()` returns `BY_STATUS`.
3. `load_grouping_mode()` returns `STANDARD` on a corrupt file (e.g. `"garbage"`).
4. `load_grouping_mode()` returns `STANDARD` on an empty file.
5. (Optional) `save_grouping_mode` returns `False` and does not raise when the parent directory is unwriteable (pytest
   `monkeypatch` to redirect `Path.home()` to a tmp path; chmod 0o500 on the tmp dir or mock `write_text` to raise
   `OSError`).

Use `tmp_path` and `monkeypatch.setattr(grouping_mode_state, "_GROUPING_MODE_FILE", tmp_path / "grouping_mode.txt")` (or
`monkeypatch.setenv("HOME", str(tmp_path))` if the existing tests use that idiom — check
`tests/ace/test_last_selection.py` for the local convention if it exists).

Add one integration assertion in `tests/ace/tui/test_agent_grouping_cycle.py`: after `action_cycle_grouping_mode()`
advances the mode, the persisted file contains the new mode's value. Use `monkeypatch` to redirect `_GROUPING_MODE_FILE`
to a tmp path. Keep this single assertion small — the dedicated unit tests in (4) own the load/save semantics.

### Step 5 — `just check`

Run `just install` (workspace setup) then `just check` per repo conventions. Verify fmt, lint, mypy, tests all pass.

## Files touched

| File                                           | Change                                                            |
| ---------------------------------------------- | ----------------------------------------------------------------- |
| `src/sase/ace/grouping_mode_state.py`          | **new** — load/save helpers                                       |
| `src/sase/ace/tui/actions/startup.py`          | call `load_grouping_mode()` to seed `_grouping_mode` and registry |
| `src/sase/ace/tui/actions/agents/_grouping.py` | call `save_grouping_mode(next_mode)` after each cycle             |
| `tests/ace/test_grouping_mode_state.py`        | **new** — unit tests for load/save                                |
| `tests/ace/tui/test_agent_grouping_cycle.py`   | one extra assertion: cycle persists                               |

## Out of scope

- **Persisting per-mode fold registries** (`_group_fold_registries`). The user asked specifically to remember the
  _grouping strategy_; persisting collapse state across restarts is a meaningful, separate feature with its own
  serialization design (registries are nontrivial dicts keyed by `tuple[str, ...]`). Worth a follow-up plan if desired,
  but it is not what was asked here.
- **Per-project grouping mode.** The Agents tab is global; there is no per-project scope to anchor to.
- **Migration.** No migration needed — the file simply doesn't exist on first run, and `load_grouping_mode()` returns
  `STANDARD` (the prior hard-coded default), so existing users see no behavior change until they cycle.
- **User-visible config knob** for "default grouping mode" in `default_config.yml`. Out of scope; the persisted value
  _is_ the user's preference, expressed via the cycle key.
- **Touching the cycle order, the help modal, or the `o` keybinding.** All unchanged.

## Open questions for the user

1. **Save-on-cycle vs. save-on-quit.** Plan picks save-on-cycle for crash-robustness and code locality. Push back if
   you'd rather match the `last_selection.txt` save-on-quit convention.
2. **File name.** Plan uses `~/.sase/grouping_mode.txt`. Alternative: `~/.sase/agents_grouping_mode.txt` if you'd like
   the "agents tab" scope encoded in the name (in case future tabs grow their own grouping).
3. **Should fold-state-per-mode also persist?** Flagged out-of-scope; mention now if you'd like it folded into this
   change instead of a follow-up.
