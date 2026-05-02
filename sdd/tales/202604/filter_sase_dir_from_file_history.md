---
create_time: 2026-04-23 15:26:02
status: draft
prompt: sdd/prompts/202604/filter_sase_dir_from_file_history.md
---

# Plan: Filter `.sase/` References Out of the Ctrl+T File-History Store

## Problem / Goal

The Ctrl+T "file history" feature (`src/sase/history/file_references.py`) records any `@`-prefixed path token it finds
in a submitted prompt. The extraction regex happily matches project-local `.sase/...` paths such as
`@.sase/home/notes.md`, `@.sase/memory/foo.md`, or `@.sase/chat/history.md`. Those entries end up in
`~/.sase/file_reference_history.json` and clutter the Ctrl+T panel with ephemeral/internal paths the user never wants to
re-reference:

- `.sase/home/<rel>` is a **copy landing zone**. It's written by `process_file_references` in the agent subprocess when
  the user writes `@~/<rel>` (see `src/sase/gemini_wrapper/file_references.py::process_file_references`). The copies are
  re-created per run — pointing Ctrl+T at them is useless; the _original_ `~/<rel>` form is the path the user mentally
  tracks.
- `.sase/memory/`, `.sase/chat/`, `.sase/cache/`, and the rest of the workspace's `.sase/` tree are agent-managed state,
  not user-edited artifacts.

**Goal:** drop any file reference whose stored form points into a project-local `.sase/` directory, both when recording
new entries and when loading the existing on-disk history. `~/` references (including `~/.sase/…`, which means the
user's _global_ sase dir, not the project-local one) must keep working — those represent deliberate user intent.

## Scope

### In scope

1. **Extraction filter.** Reject references whose post-`@`-strip form starts with `.sase/`.
2. **Load-side filter.** Skip `.sase/` entries already sitting in `file_reference_history.json` so they disappear from
   the Ctrl+T panel immediately. Subsequent `record_file_references` calls naturally rewrite the file without them
   (because record = load + prepend + dedup + write), giving us a free one-pass cleanup on the next prompt submission.
3. **Tests.** New assertions on `extract_recordable_file_refs` for `.sase/` tokens (bare and `@`-prefixed), a load-side
   test for historical `.sase/` entries being filtered, and a round-trip test confirming that a `record_file_references`
   call scrubs pre-existing `.sase/` entries off disk.

### Out of scope

- Filtering `.sase/` _content references_ that reach the agent subprocess via `process_file_references`. That path is
  what writes files to `.sase/home/` in the first place and must keep doing so — we're only trimming the _history_
  feature, not the prompt rewrite.
- Changing the extraction regex's accepted shape. The regex stays; the filter is an extra predicate applied to its
  output.
- Migration of the existing `file_reference_history.json`. No one-shot migration script is needed — load-side filtering
  makes existing stale entries invisible, and the very next `record_file_references` call rewrites the file without
  them.
- Any change to `remove_file_reference`. It already takes an exact stored-form string, and filtering happens at
  read/write boundaries; removal logic is unaffected.

## High-Level Design

### Recording direction

Touchpoint: `extract_recordable_file_refs` in `src/sase/history/file_references.py`.

Today the function walks `_FILE_REF_RE` matches and keeps a path when either (a) it had an `@` prefix, or (b) it starts
with `/` or `~/`. Both branches will additionally be guarded by a new helper:

```python
def _is_local_sase_path(path: str) -> bool:
    """True if *path* points into a project-local `.sase/` directory."""
    return path.startswith(".sase/")
```

Important nuances:

- `path` at this point is the raw token with `@` already stripped. So `@.sase/home/x.md` becomes `.sase/home/x.md` which
  matches.
- `~/.sase/foo` does **not** start with `.sase/` — it starts with `~/.sase/foo` — so it is kept. This is correct: that
  refers to the user's _global_ sase dir (e.g., `~/.sase/projects/...`), which is legitimate user-facing data.
- `/home/user/proj/.sase/foo` does not start with `.sase/` either; it's an absolute path. We deliberately keep it. If a
  user spells out an absolute path into a `.sase` subtree they've opted into specifying it literally, and it's ambiguous
  whether that's "internal" — err on the side of keeping user-typed absolute paths.
- `./.sase/foo` is not emitted by the existing regex (the `./` branch requires a word character after the slash, and
  `.sase` starts with a dot, so the `./foo` alternative doesn't match `.`). Confirm during implementation; if the regex
  does match it, extend the filter to normalize `./` → empty before comparing.

### Load direction

Touchpoint: `load_file_references` in the same module. After the current `isinstance(p, str)` filter, drop entries
matching `_is_local_sase_path`:

```python
return [p for p in paths if isinstance(p, str) and not _is_local_sase_path(p)]
```

Because `record_file_references` calls `load_file_references`, then prepends + dedups + writes, any pre-existing
`.sase/` entries silently fall off disk on the next submitted prompt. No migration script; the write path _is_ the
migration.

### Completion builder

`build_file_history_completion_candidates` (`src/sase/ace/tui/widgets/file_completion.py`) calls `load_file_references`
and turns each entry into a candidate. With load-side filtering in place, `.sase/` entries never reach the panel. No
changes needed here.

## Files Touched (summary)

| Kind | Path                                    | Reason                                                        |
| ---- | --------------------------------------- | ------------------------------------------------------------- |
| Edit | `src/sase/history/file_references.py`   | Add `_is_local_sase_path`; apply in extract + load            |
| Edit | `tests/history/test_file_references.py` | New extraction cases, load-side filter test, round-trip scrub |

No other files need to change. The Ctrl+T UI, `record_file_references`, and `remove_file_reference` inherit the new
behavior for free through the load path.

## Testing Strategy

- **Unit: extraction.**
  - `@.sase/home/foo.md` → excluded.
  - `@.sase/memory/x.md` → excluded.
  - `.sase/home/foo.md` (no `@`) → still excluded (already excluded today; regression guard).
  - `@~/.sase/projects/foo.gp` → **kept** (global sase dir, not project-local).
  - `@~/notes.md` → kept (baseline sanity).
- **Unit: load-side filter.**
  - Write a `file_reference_history.json` containing `["/etc/hosts", ".sase/home/a.md", "~/b.md"]`; assert
    `load_file_references` returns `["/etc/hosts", "~/b.md"]`.
- **Unit: round-trip scrub.**
  - Seed a history file containing a `.sase/` entry, call `record_file_references(["/new"])`, reload the _raw_ JSON from
    disk, and assert the `.sase/` entry is gone while `/new` and the surviving real entries remain in the right order.
- **Unit: preserve existing behavior.**
  - Every existing `TestExtractRecordableFileRefs` / `TestFileReferenceStore` case in
    `tests/history/test_file_references.py` still passes — the filter is strictly additive, so existing green cases
    should stay green.

## Open Questions

1. **Treat `.sase` (no trailing slash) as a match?** A bare token like `@.sase` is unlikely in practice and the regex
   doesn't emit it without a trailing path segment anyway. Proposal: keep the filter as a prefix check on `.sase/`;
   revisit only if a real case shows up.
2. **Case sensitivity.** Linux-only filesystem usage in this project means `.sase/` vs `.SASE/` isn't a realistic
   concern. Keep the comparison case-sensitive.
3. **Absolute paths into a project's `.sase/`** (e.g., `/home/bryan/proj/.sase/home/foo.md`). Proposal: keep — rationale
   in the High-Level Design. Call out in review if we want to tighten later.

## Risks / Non-Risks

- **Low risk; purely subtractive.** The change only removes entries from a display-only history. No prompt, no on-disk
  artifact, and no agent behavior is affected.
- **Privacy:** improves slightly — fewer ephemeral internal paths recorded to disk.
- **Backwards compat:** existing history files stay readable; `.sase/` entries are silently skipped on load and cleaned
  up on the next write. No user-visible breakage.
- **Concurrency:** unchanged. Still last-writer-wins as with the rest of the history modules.
