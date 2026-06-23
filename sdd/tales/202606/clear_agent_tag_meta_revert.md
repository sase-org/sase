---
create_time: 2026-06-23 08:25:59
status: done
prompt: sdd/prompts/202606/clear_agent_tag_meta_revert.md
---
# Fix: Clearing an agent's group/tag reverts when the agent name contains `<group>.`

## Problem statement

On the Agents tab of the `sase ace` TUI, pressing `N` and submitting an **empty** input is supposed to clear an agent's
group/tag, moving its row into the `(untagged)` panel. For agents whose name contains a `<group_name>.` prefix (e.g. an
agent named `foo.bar`), the clear _appears_ to work — the row jumps to `(untagged)` immediately — but **a moment later
the row snaps back to its original group**. Clearing works correctly for agents whose name does **not** match a group.

## Root cause

The agent's user-facing tag is persisted in **two independent stores**, and the clear operation only mutates one of
them:

1. **`~/.sase/agent_tags.json`** — the user-managed tag store (`src/sase/ace/agent_tags.py`). This is the _only_ store
   the `N` keymap mutates. Clearing calls `unset_tag()`, which **deletes** the agent's identity entry, then
   `save_agent_tags()`.

2. **`agent_meta.json`** in the agent's artifacts dir — written **at launch** by `src/sase/axe/run_agent_directives.py`:
   - Lines 199–206: when no explicit `%tag`/`%group` directive is given, the launch code **derives** a tag from the
     agent name via `match_existing_name_group(agent_name, load_agent_tags().values())`. This returns a group when the
     name equals a group or starts with `<group>.` (so `foo.bar` → `foo`).
   - Lines 235–236: `agent_meta["tag"] = agent_tag` — the derived (or explicit) tag is written into `agent_meta.json`.

On every Agents-tab (re)load the tag is resolved in this order:

1. A fresh `Agent` is created with `tag = None` (`src/sase/ace/tui/models/agent.py:249`).
2. **Meta enrichment** sets `agent.tag` from `agent_meta.json`:
   - `src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py:65-67`
   - `src/sase/ace/tui/models/_loaders/_meta_enrichment_wire.py:53-54`
3. **Disk projection override** in `src/sase/ace/tui/actions/agents/_loading_helpers.py:308-310` applies the user store
   _only if the identity is present_:
   ```python
   if agent.identity in tags_by_identity:
       agent.tag = tags_by_identity[agent.identity]
   ```

This makes `agent_meta.json` the **base** value and `agent_tags.json` an **override-if-present**. The two paths behave
asymmetrically:

- **Setting/renaming** a tag via `N` works because the override is _present_ in `agent_tags.json`, so step 3 wins over
  the stale meta value.
- **Clearing** a tag via `N` fails because `unset_tag()` _deletes_ the entry. On the next periodic refresh
  (`_on_auto_refresh` → reload), step 2 restores `agent.tag = "foo"` from `agent_meta.json`, and step 3 does **not**
  override (identity absent). The row snaps back to `foo`.

**Why only `<group_name>.` names:** that prefix condition is exactly when `match_existing_name_group` returns non-`None`
at launch, which is the only way an agent the user never explicitly tagged ends up with a `tag` field in
`agent_meta.json`. Agents whose `agent_meta.json` has no `tag` clear correctly, because step 2 leaves
`agent.tag = None`.

The panel grouping itself is driven purely by `agent.tag` (`src/sase/ace/tui/models/agent_panels.py:36` →
`target.tag if target.tag else None`), so once `agent.tag` resolves to `None` and _stays_ `None`, the row sits in
`(untagged)` permanently. The name-family logic in `src/sase/ace/tui/models/agent_groups/_keys.py` only sub-groups
_within_ a panel and is **not** the cause.

### Generalization

The bug is not strictly limited to dotted names. **Any** agent whose `agent_meta.json` carries a `tag` (name-derived
_or_ an explicit `%group`/`%tag` launch directive) will snap back on clear. The dotted-name case is simply the most
common one the user hits, because those agents get auto-tagged silently. The fix below resolves all of these uniformly.

## Fix

**Make "clear" reverse _both_ writes that created the tag.** When the user clears an agent's tag, in addition to
removing the entry from `agent_tags.json`, **strip the `tag` field from that agent's `agent_meta.json`** so the two
stores agree and the meta value can no longer resurrect the tag on reload.

This is the principled inverse of how the tag is created: launch writes the derived tag to _both_ stores, so clearing
must clear _both_. It leaves the load/projection semantics — which the working _set/rename_ path depends on — completely
untouched, and it introduces no regression for cl-less agents, review-tagged agents (`REVIEW_AGENT_TAG`), or pinned
agents (`DEFAULT_PINNED_TAG`), because those paths are not altered.

### Implementation outline

1. **Add a meta-tag strip helper** alongside the existing meta read/write helpers in `src/sase/axe/runner_utils.py`
   (which already hosts `read_agent_meta` and the `write_agent_meta` family):
   - `clear_agent_meta_tag(artifacts_dir: str) -> bool`
   - Read `agent_meta.json`, and if it contains a `tag` key, remove **only** that key (preserving all other fields),
     then write it back using the existing atomic write path. No-op (return `False`) when the file is missing,
     unreadable, or has no `tag`. Never raise on I/O/JSON errors — clearing a tag must not crash the TUI.

2. **Call the helper from the clear path** in `src/sase/ace/tui/actions/agents/_tagging.py` (`_apply_agent_tag_change`,
   the `result.action == "unset"` branch, around lines 122–136). For each affected agent that has an artifacts dir
   (`agent.get_artifacts_dir()`), strip its meta tag right after `unset_tag(store, agent.identity)`. Keep the existing
   in-memory `candidate.tag = None`, `save_agent_tags(store)`, cache invalidation, and refresh. Use a lazy import
   (consistent with the file's existing import style).

3. **Multi-agent / marked-set correctness:** the clear path already iterates over all `affected` agents; the meta strip
   must run once per affected agent, so it composes naturally with marked-multi-clear.

### Considerations / edge cases to handle in implementation

- **Running agents & merge writers.** Several `write_agent_meta` callers (`run_agent_markers.py`, `run_agent_wait.py`)
  merge the _existing on-disk_ `agent_meta.json` with new fields. Because tag derivation happens **only** at launch in
  `run_agent_directives.py` (never mid-run), a merge writer that runs after the strip will read the already-stripped
  meta and **preserve** the tag-less state rather than re-derive it. The strip is therefore durable for both terminal
  and running agents. (Terminal agents have no live process and are fully safe.)
- **Both loaders covered.** Filesystem and wire meta enrichment both ultimately read the same on-disk `agent_meta.json`,
  so stripping the on-disk file fixes both loading paths.
- **Set/rename path unchanged.** The set path does not write `agent_meta.json`; it relies on the override and continues
  to work. (Optional hardening, out of primary scope: also mirror the tag into `agent_meta.json` on _set_ so both stores
  always agree. Not required to fix this bug; note it but do not block on it.)

## Alternatives considered (and why not)

- **Tombstone in `agent_tags.json` (record "explicitly cleared").** Make the projection step authoritative by persisting
  a cleared marker so absence vs. cleared can be distinguished. Rejected: it breaks the store's clean invariant
  ("untagged identities are simply absent") and complicates the file format and the set/unset logic for a case the
  meta-strip handles more directly.
- **Make `agent_tags.json` the single source of truth (drop the meta `tag` from display / stop writing it at launch).**
  Rejected as the primary fix: larger blast radius across launch + both loaders, and a real regression risk for agents
  launched without a `cl_name` (where `run_agent_directives.py:278` skips the `agent_tags.json` write and
  `agent_meta.json` is currently the only tag carrier). Worth revisiting as a separate cleanup but not needed to fix
  this bug.

## Boundary note

There is no agent-tag logic in the sibling Rust core (`../sase-core`); the tag store (`agent_tags.py`), the launch
derivation, and the loaders are all Python/TUI-side. This fix stays entirely within this repo and does not cross the
Rust core boundary.

## Testing

- **Helper unit test** (near the existing `runner_utils`/meta tests): writing an `agent_meta.json` with `tag` plus other
  fields, then `clear_agent_meta_tag`, removes only `tag` and preserves the rest; missing file, missing `tag`, and
  malformed JSON are safe no-ops.
- **Regression test reproducing the bug** (in the ACE TUI tagging tests, alongside the existing agent-tag tests): given
  an agent named `foo.bar` whose `agent_meta.json` has `tag: "foo"` and no `agent_tags.json` entry, simulate the clear
  and then a reload (meta enrichment + disk projection) and assert the resolved `agent.tag` is `None` (row lands in
  `(untagged)` and stays). Add the symmetric assertion that before the fix it reverts.
- **No-regression checks:** clearing an agent that has no meta `tag` is a no-op; setting/renaming a tag still wins on
  reload; clearing across a marked multi-selection strips each agent's meta tag.
- Extend `tests/test_agent_tags.py` only if a new shared helper lands in `agent_tags.py`; otherwise keep helper tests
  next to `runner_utils`.
- Run `just check` (after `just install`) before completion.

## Files involved

- `src/sase/axe/runner_utils.py` — new `clear_agent_meta_tag` helper (read-modify-write of `agent_meta.json`).
- `src/sase/ace/tui/actions/agents/_tagging.py` — call the helper in the `unset` branch of `_apply_agent_tag_change`.
- `src/sase/axe/run_agent_directives.py:199-206,235-236` — reference only (the source of the dual write); no change
  required by the primary fix.
- `src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py`, `_meta_enrichment_wire.py`,
  `src/sase/ace/tui/actions/agents/_loading_helpers.py` — reference only (the load/projection ordering that produces the
  symptom).
- Tests: ACE TUI tagging test module + `runner_utils`/meta test module (and `tests/test_agent_tags.py` if a shared
  helper is added there).
