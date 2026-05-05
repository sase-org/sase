---
create_time: 2026-05-05 16:14:19
status: done
prompt: sdd/prompts/202605/changespec_deltas_v_keymap.md
---
# Plan: Support DELTAS file entries in the `v` keymap

## Goal

When the user presses `v` on a ChangeSpec in `sase ace`, file entries rendered under the ChangeSpec `DELTAS:` section
should participate in the existing file-hint workflow. A visible delta entry such as:

```text
  ~ java/com/example/Foo.java
```

should become selectable with a numbered hint, and inputs like `3`, `3@`, `3%`, or `1-3` should view, edit, or copy
those paths through the existing `v` keymap behavior.

## Current behavior

- `v` on the CL tab calls `FileViewingMixin.action_view_files()`.
- That re-renders `ChangeSpecDetail.update_display_with_hints(..., hints_for=None)`.
- `ChangeSpecDetail._build_display_content()` threads a `HintTracker` through section builders.
- `COMMITS`, `HOOKS`, `COMMENTS`, and `MENTORS` can add mappings into the tracker.
- `DELTAS` renders file paths in `src/sase/ace/tui/widgets/deltas_builder.py`, but `build_deltas_section()` currently
  returns the hint tracker unchanged by design.
- `parse_view_input()` and `_process_view_input()` already handle ranges, editor suffix `@`, copy suffix `%`, invalid
  hints, and de-duplication once hint mappings exist.

## Scope

This is a TUI presentation/keymap integration change. No Rust core parser work is needed because `DeltaEntry` already
exists in the Python model and Rust wire parser, and the `DELTAS` section is already parsed and rendered.

## Design

1. Extend `build_deltas_section()` to optionally render file hints.
   - Add a `show_file_hints: bool = False` argument.
   - Add a `workspace_dir: str | None = None` argument for resolving relative delta paths.
   - Preserve the current default output exactly when hints are not requested.
   - Keep collapsed `DELTAS` as summary-only. Only actual visible file entry lines get hints.

2. Add a small path resolver for delta entries.
   - Absolute paths and `~` paths should resolve directly.
   - Repo-relative delta paths should resolve under the selected ChangeSpec's primary workspace when available.
   - If workspace resolution fails, fall back to the existing current-working-directory behavior for relative paths
     rather than failing hint rendering.
   - Reuse existing helpers where practical instead of inventing a separate workspace model.

3. Thread hint mode from `ChangeSpecDetail` into the DELTAS builder.
   - `show_delta_hints = with_hints and hints_for in (None, "all")`.
   - Resolve the ChangeSpec workspace once in `_build_display_content()` only when delta hints are needed.
   - Pass `show_delta_hints`, `workspace_dir`, and the current `HintTracker` into `build_deltas_section()`.

4. Update `DELTAS` line rendering.
   - Render the hint marker before the path, after the glyph, matching nearby file-hint style:
     ```text
       ~ [3] java/com/example/Foo.java
     ```
   - Add the resolved path to `hint_mappings[hint_counter]`.
   - Increment `hint_counter` per visible delta entry.
   - Keep line stats rendering unchanged after the path.

5. Add focused tests.
   - `tests/ace/tui/test_deltas_builder.py`:
     - verifies expanded DELTAS emits hints and mappings.
     - verifies relative paths resolve under `workspace_dir`.
     - verifies absolute and `~` paths are preserved/expanded sensibly.
     - verifies collapsed DELTAS does not add hidden file hints.
     - verifies hint counters continue from an incoming tracker after prior section hints.
   - A `ChangeSpecDetail` level test if existing test harness makes it cheap:
     - `update_display_with_hints()` returns DELTAS mappings when DELTAS is expanded.
     - This protects the actual `v` keymap path, not just the section builder.

6. Verification.
   - Run the focused DELTAS and file-hint tests first.
   - Run broader relevant TUI tests if focused tests pass.
   - Per repo instructions, run `just install` if needed and `just check` before final response after code changes.

## Risks and decisions

- Collapsed DELTAS should not expose hidden files as hints. The `v` mode numbers visible detail entries today, so
  preserving visibility semantics avoids surprising jumps from a summary line to many hidden files.
- The primary workspace is the best target for repo-relative delta files in a ChangeSpec detail view. This aligns with
  other ChangeSpec operations that use workspace number 1 for read-only/default operations.
- If the workspace cannot be resolved, falling back to `os.path.abspath()` keeps the feature usable in tests,
  nonstandard project files, and local development without turning hint rendering into a fatal path lookup.
