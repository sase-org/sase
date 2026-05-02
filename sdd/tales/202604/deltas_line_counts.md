---
create_time: 2026-04-30 10:23:52
status: done
prompt: sdd/prompts/202604/deltas_line_counts.md
---
# Plan: DELTAS Line Counts

## Goal

Extend the ChangeSpec `DELTAS` section so every file entry can show how many lines were added, modified, or removed, and
keep those counts refreshed whenever the `COMMITS` list changes.

This should feel like a natural evolution of the existing DELTAS field: compact on disk, backward-compatible for older
ChangeSpecs, and visually clear in CLI / ACE. The current DELTAS refresh pipeline is already called after commit entry
creation, proposal accept/renumber, rewind, sync, and parent rebase. This work should enrich that pipeline rather than
introducing a separate update mechanism.

## Design

### On-Disk Format

Keep the path entry line exactly as it is today and attach line counts as a small drawer line under that entry:

```text
DELTAS:
  + src/sase/new_file.py
      | LINES: +128
  ~ src/sase/existing.py
      | LINES: +12 ~7 -3
  - src/sase/old_file.py
      | LINES: -44
```

Reasons:

- Preserves the existing `  <glyph> <path>` format, so paths with spaces continue to parse without guessing where
  metadata starts.
- Older parsers already ignore six-space drawer lines in `DELTAS`, so this is a graceful forward-compatible extension.
- It matches the visual language already used by `COMMITS` drawers (`CHAT`, `DIFF`, `PLAN`) without making each path
  line harder to parse.

For binary files, emit:

```text
      | LINES: binary
```

Old entries with no `LINES` drawer remain valid and parse as `line_stats=None`.

### Data Model

Add a small line-stat model and attach it to `DeltaEntry`:

```python
@dataclass
class DeltaLineStats:
    added: int = 0
    modified: int = 0
    removed: int = 0
    binary: bool = False

@dataclass
class DeltaEntry:
    path: str
    change_type: str
    line_stats: DeltaLineStats | None = None
```

The stored counts should be semantic counts:

- `added`: net newly inserted lines.
- `modified`: changed lines, derived as paired additions/deletions.
- `removed`: net deleted lines.
- `binary=True`: VCS cannot provide line counts.

For text diffs, Git-style numstat gives raw additions/deletions. Convert to semantic counts with:

- `modified = min(raw_added, raw_removed)`
- `added = raw_added - modified`
- `removed = raw_removed - modified`

That makes a one-line edit display as `~1`, a one-line-to-three-lines edit display as `+2 ~1`, and a pure insertion
display as `+N`.

### VCS Integration

Add a VCS-provider query for line stats between the same parent/head refs used by `compute_deltas`:

```python
diff_line_stats(parent_ref, head_ref, cwd) -> list[tuple[str, str, str]]
```

where each row is `(raw_added, raw_removed, path)`, and `raw_added/raw_removed` may be `"-"` for binary files.

For the built-in Git provider, implement this with `git diff --numstat -z <parent>..<head>` and a parser in the
`sase.core.git_query_*` facade family, matching the existing `parse_git_name_status_z` style. Keep process execution in
the provider; keep pure parsing in the facade. Add Python golden tests for the parser, including:

- normal text files
- paths with spaces
- binary files (`-` / `-`)
- rename/copy rows in Git's NUL format
- malformed/truncated rows ignored rather than crashing

`compute_deltas` should call both `diff_name_status` and `diff_line_stats`, then merge by path after the existing status
mapping. If a provider does not implement line stats, keep DELTAS entries and set `line_stats=None`; refresh should stay
best-effort and non-blocking.

### Rename / Copy Behavior

Retain the existing file-level behavior:

- rename: source path becomes `D`, target path becomes `A`
- copy: target path becomes `A`

Line stats come from the target path's numstat row when available. A pure rename can therefore show zero content-line
changes, which is accurate: the file moved, but its content did not change. If this looks too quiet in ACE, rendering
can dim the `0 lines` text rather than inventing fake added/removed counts.

### Rendering

CLI full DELTAS rendering:

```text
DELTAS:
  + src/sase/new_file.py              +128
  ~ src/sase/existing.py              +12 ~7 -3
  - src/sase/old_file.py              -44
```

ACE fully-expanded rendering should use the existing glyph colors and add right-side line-count tokens:

- `+N` in the same green as added files
- `~N` in the same gold as modified files
- `-N` in the same red as deleted files
- `binary` in dim italic gray

ACE expanded summary should include both file counts and line counts:

```text
DELTAS:  +3 (+428)  ~6 (+91 ~37 -14)  -1 (-22)  (10 files)
```

Keep zero values out of the visual display unless all counts are zero, in which case show `0 lines` dimmed.

### Refresh Contract

The rule should be documented as:

> Any code path that changes the `COMMITS` list, accepted proposal set, parent base, or VCS head used by a ChangeSpec
> must call `refresh_deltas_for_changespec()` after the atomic write.

The existing hooks already call it after:

- normal commit entry creation
- proposed commit entry creation
- proposal accept / COMMITS renumber
- rewind
- sync
- parent rebase
- manual `sase changespec sync-deltas`

During implementation, audit all `COMMITS` writers and either confirm they are metadata-only (suffix/status changes that
do not affect the file diff) or add a refresh call when they can change the effective file set. Prefer one shared
best-effort helper for post-COMMITS refresh so future writers do not copy/paste silent `try/except` blocks.

## Implementation Phases

### Phase 1: Model, Parser, Formatter

- Add `DeltaLineStats` and `DeltaEntry.line_stats`.
- Extend DELTAS parsing to associate `      | LINES: ...` with the preceding delta entry.
- Keep old `DELTAS` entries without drawers parsing cleanly.
- Extend `format_deltas_field()` to emit compact line drawer lines when stats are present.
- Add round-trip tests for old and new formats.

### Phase 2: VCS Line Stats

- Add VCS provider / hookspec / plugin-manager methods for `diff_line_stats`.
- Implement Git via `git diff --numstat -z`.
- Add parser facade and tests for numstat output.
- Make unsupported providers degrade gracefully to `line_stats=None`.

### Phase 3: Compute Merge

- Update `compute_deltas()` to merge name-status entries with numstat rows.
- Add unit tests for added, modified, deleted, binary, copy, rename, and missing-stat cases.
- Confirm existing `refresh_deltas_for_changespec()` continues preserving the prior DELTAS body on VCS errors.

### Phase 4: Presentation

- Update CLI `display_changespec()` rendering to show inline line-count tokens.
- Update ACE `deltas_builder` fully-expanded and expanded summary states.
- Add focused rendering tests that assert visible text for line stats without overfitting Rich styles.
- Update `docs/change_spec.md` and `docs/ace.md`.

### Phase 5: Refresh Audit

- Audit all `COMMITS` mutation helpers.
- Add or centralize a post-COMMITS DELTAS refresh helper where needed.
- Add regression coverage for a commit/proposal update path proving refreshed DELTAS includes line counts after the
  `COMMITS` entry is written.

## Verification

Run focused tests first:

```bash
just install
uv run pytest tests/test_deltas_parsing.py tests/test_deltas_compute.py tests/ace/tui/test_deltas_builder.py
```

Then run the required repo check before finishing:

```bash
just check
```

## Non-Goals

- Do not add a new timestamp event for DELTAS refreshes; this would make `TIMESTAMPS` noisy.
- Do not hand-edit generated `COMMITS` entries.
- Do not make line stats a hard dependency for DELTAS refresh; unsupported providers should still show file-level
  DELTAS.
