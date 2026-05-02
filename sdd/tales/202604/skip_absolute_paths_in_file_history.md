---
create_time: 2026-04-25 09:44:53
status: draft
prompt: sdd/prompts/202604/skip_absolute_paths_in_file_history.md
---

# Plan: Skip Recording `/`-Prefixed Paths in the Ctrl+T File-History Store

## Problem / Goal

The Ctrl+T "file history" feature (`src/sase/history/file_references.py::extract_recordable_file_refs`) records two
flavors of path tokens it pulls out of a submitted prompt:

1. `@`-prefixed paths — the `@` is stripped (`@src/foo.py` → `src/foo.py`).
2. Absolute paths — tokens that start with `/` or `~/` (`/etc/hosts`, `~/notes.md`).

Bare absolute paths beginning with `/` (e.g. `/etc/hosts`, `/tmp/a.txt`, or an `@`-stripped form like `@/tmp/a.txt` →
`/tmp/a.txt`) tend to be one-off system-ish references the user does not want to revisit through `<ctrl+t>` completion.
They drown out the entries that are actually useful: `~/`-rooted paths the user keeps in their head and `@`-prefixed
project-relative paths the user explicitly tagged.

**Goal:** drop any extracted file reference whose final stored form starts with `/`. Keep `~/`-rooted paths and `@`-
prefixed non-`/` paths exactly as today. The change is recording-side only — old `/`-prefixed entries already on disk
are out of scope.

## Scope

### In scope

1. **Extraction filter.** Reject references whose post-`@`-strip form starts with `/`. This replaces the existing
   `path.startswith(("/", "~/"))` branch (which has been the _only_ way bare absolute paths entered the store),
   narrowing it to just `~/`. The `@`-prefixed branch still runs but now also rejects `@/...` tokens.
2. **Tests.** Update `tests/history/test_file_references.py` to reflect the new contract:
   - `extract_recordable_file_refs` no longer returns `/`-prefixed paths.
   - Existing storage / load / remove mechanics are untouched (they bypass extract; pre-existing `/` paths still load).

### Out of scope

- **Load-side filtering** of pre-existing `/`-prefixed entries. The user only asked to stop _saving_ new ones. Sweeping
  pre-existing entries off disk would surprise users who have legitimate `/`-rooted history they want to keep around. We
  can revisit later if it turns out to be a wart.
- **`record_file_references` / `remove_file_reference` filtering.** Both already accept exact stored-form strings and
  must keep doing so — many existing storage tests pass `["/a", "/b"]` directly and exercise dedup/order/round-trip
  logic. Filtering at the storage boundary would force a sweeping test rewrite for no behavior win (extract is the only
  caller in product code).
- **Display-side regex** in `sase.ace.tui.widgets.prompt_panel._file_path_hints`. That regex powers prompt-time
  highlighting, not history; leave it alone.
- **Migration script** for the existing `~/.sase/file_reference_history.json`. Per "out of scope" #1 above, no
  migration; existing entries persist organically.
- **Filtering of `@/...` tokens that decay to plain absolute paths in history.** Once `@` is stripped, these are
  indistinguishable from bare `/...` references — the new filter catches them uniformly, which is the desired behavior.

## High-Level Design

### Recording direction

Touchpoint: `extract_recordable_file_refs` in `src/sase/history/file_references.py`.

Today the function walks `_FILE_REF_RE` matches and keeps a path when either (a) it had an `@` prefix, or (b) it starts
with `/` or `~/`. The two-line change:

```python
for match in _FILE_REF_RE.finditer(text):
    at_prefix = match.group(1)
    path = match.group(2)
    if _is_local_sase_path(path):
        continue
    if path.startswith("/"):           # NEW: skip absolute /-paths regardless of @ prefix
        continue
    if at_prefix:
        results.append(path)
    elif path.startswith("~/"):        # was: startswith(("/", "~/"))
        results.append(path)
```

Important nuances:

- `path` is the raw token with `@` already stripped, so `@/tmp/a.txt` arrives as `/tmp/a.txt` and is skipped. This is
  the desired symmetry: whether the user typed `/tmp/a.txt` or `@/tmp/a.txt`, the stored form would be `/tmp/a.txt`,
  which the user has now told us they don't want in history.
- `~/foo` is unaffected — it does not start with `/`. (The leading char is `~`.)
- `@~/foo` → after `@` strip → `~/foo` → still kept via the `at_prefix` branch.
- Bare `~` alone is already filtered out today; that doesn't change.
- Project-local `.sase/` filtering still runs first and remains intact.

### Load / remove direction

No changes. `load_file_references` keeps returning whatever's in the JSON minus `.sase/` entries. Pre-existing
`/`-rooted entries continue to load — that's the explicit "out of scope" decision in §Scope.

### Completion builder, agent launch, and prompt bar

`build_file_history_completion_candidates` and the two call sites in `_agent_launch.py` / `_prompt_bar_mount.py` consume
`extract_recordable_file_refs` output and inherit the new behavior for free. No edits.

## Files Touched (summary)

| Kind | Path                                    | Reason                                                                                                          |
| ---- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Edit | `src/sase/history/file_references.py`   | Drop `/` from the kept-absolute set; let `@/...` fall through the new filter                                    |
| Edit | `tests/history/test_file_references.py` | Adjust `TestExtractRecordableFileRefs` cases that currently expect `/`-prefixed entries; add explicit skip case |

No other files change. The Ctrl+T UI, agent launch, and prompt-bar mount paths all funnel through
`extract_recordable_file_refs`.

## Testing Strategy

- **Update existing extraction tests** so their expectations match the new contract:
  - `test_keeps_absolute_and_tilde_paths` — rename to `test_keeps_tilde_paths_drops_absolute`; expect only
    `["~/notes/ideas.md"]` from `"check /etc/hosts and ~/notes/ideas.md please"`.
  - `test_includes_at_prefixed_tilde_and_absolute` — rename to `test_drops_at_prefixed_absolute_keeps_others`;
    `"@~/notes.md @/tmp/a.txt @docs/x.md"` → `["~/notes.md", "docs/x.md"]`.
  - `test_preserves_prompt_order` — `"second ~/b first: /a and @c/d.py last"` → `["~/b", "c/d.py"]` (drop the `/a`).
- **New regression tests:**
  - `test_drops_bare_absolute_paths`: `"see /etc/hosts please"` → `[]`.
  - `test_drops_at_prefixed_absolute_paths`: `"see @/etc/hosts please"` → `[]`.
  - `test_keeps_tilde_after_change`: `"~/notes.md"` and `"@~/notes.md"` both kept.
- **Storage / load / remove tests are unchanged.** They feed `record_*` directly with `["/a", "/b"]` and exercise
  dedup/order/remove mechanics — that contract still holds. (If we ever decide to filter on load, those tests would need
  to be revisited; today they don't.)
- **Manual smoke test:** run `just check`; submit a prompt containing `@/tmp/foo` and `/etc/hosts` in the TUI; confirm
  via `sase file-history list` that neither path was recorded, while a sibling `~/notes.md` reference was.

## Open Questions

1. **Should we also scrub pre-existing `/`-prefixed entries on load?** The plan says no (out of scope). If feedback in
   review says "yes, clear them out," it's a one-line addition to `load_file_references` mirroring the `.sase/` pattern
   plus a load-side test — small follow-up, easy to do later.
2. **Symmetry with `@/...`.** Confirmed in High-Level Design: once `@` is stripped, `@/foo` is indistinguishable from
   `/foo` and is filtered. This matches the user's "individual path starts with `/`" framing. If the user actually
   wanted to _keep_ `@/...` because the `@` signals intent, that would require carrying the `@`-prefix flag through and
   is a bigger change — flag in review if so.

## Risks / Non-Risks

- **Low risk; purely subtractive on the recording side.** No prompt processing, on-disk schema, or agent behavior is
  affected — only what makes it into the history JSON.
- **Backwards compat:** existing history files stay fully readable; `/`-rooted entries persist on load and through
  `record_file_references` round-trips. Users with a long Ctrl+T history don't lose anything.
- **Privacy / hygiene:** improves marginally — fewer system-ish paths recorded to disk.
- **Concurrency:** unchanged. Still last-writer-wins on `~/.sase/file_reference_history.json`.
