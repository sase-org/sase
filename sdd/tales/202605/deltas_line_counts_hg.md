---
create_time: 2026-05-05 16:25:28
status: wip
prompt: sdd/prompts/202605/deltas_line_counts_hg.md
---
# Plan: Show DELTAS Line Counts for Mercurial ChangeSpecs

## Context

The core `sase` repo already has most of the DELTAS line-count plumbing:

- `DeltaLineStats` and `DeltaEntry.line_stats` exist in `src/sase/ace/changespec/models.py`.
- DELTAS parsing/formatting supports `      | LINES: ...` drawers.
- `compute_deltas()` asks the active VCS provider for `diff_line_stats()` and attaches the stats when available.
- Git implements `vcs_diff_line_stats()` using `git diff --numstat`.
- ACE already renders per-entry line stats inline when `line_stats` is populated.
- COMMITS append paths call `refresh_deltas_after_commits_change()` after adding entries.

The provided `sase ace` snapshot is from the Google/Mercurial workflow. The `retired Mercurial plugin` plugin currently implements
`vcs_diff_name_status()` but does not implement `vcs_diff_line_stats()`, so core degrades to file-only DELTAS and ACE
has no line-count data to display.

## Goal

When a ChangeSpec is backed by the Google/Mercurial provider, DELTAS entries should include line-count stats after
DELTAS refreshes, including refreshes triggered by newly added COMMITS entries.

Example target shape on disk:

```text
DELTAS:
  ~ java/com/example/Foo.java
      | LINES: +3
  ~ java/com/example/Bar.java
      | LINES: +2 ~7 -1
```

ACE will then render the file entries with the existing inline stats, for example:

```text
  ~ java/com/example/Foo.java  +3
```

## Implementation

1. Add Mercurial line-stat support in `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`.
   - Implement `vcs_diff_line_stats(parent_ref, head_ref, cwd)`.
   - Use the same revision pair as `vcs_diff_name_status()`.
   - Prefer a command shape based on `hg diff --stat` or another locally available Mercurial diff output that can be
     parsed in tests without requiring Google-only services.
   - Return rows matching the core contract: `(raw_added, raw_removed, path)`.
   - For binary entries, return `("-", "-", path)` if the selected hg output exposes that reliably; otherwise omit
     binary stats and let core preserve file-level DELTAS.
   - Raise `VCSOperationError("diff_line_stats", ...)` on command failure, matching the Git provider behavior.

2. Keep core behavior unchanged unless inspection reveals a display bug.
   - Do not alter the on-disk DELTAS format unless required.
   - Do not add a new timestamp for DELTAS refresh.
   - Do not make line stats mandatory; unsupported or unparsable rows should degrade to file-level DELTAS.

3. Add plugin unit tests in `../retired Mercurial plugin/tests/test_hg_plugin.py`.
   - Success: verifies command invocation and parsing of added/removed counts for several paths.
   - Failure: verifies a failed hg command raises `VCSOperationError` with operation `diff_line_stats`.
   - Include at least one path with spaces if the chosen output format can represent it unambiguously.

4. Add or update core regression coverage only if needed.
   - Existing core tests already prove `add_commit_entry_with_id()` refreshes DELTAS after adding COMMITS entries and
     that line stats are persisted.
   - If plugin integration requires a core-side assumption, add a focused test in the core repo; otherwise avoid churn.

5. Verification.
   - Run focused core tests for DELTAS parsing/compute/TUI/commit refresh.
   - Run focused `retired Mercurial plugin` plugin tests.
   - Because both repos are touched, run `just check` in each modified repo after `just install` where required.

## Risks and Constraints

- Mercurial stat output can be less structured than Git `--numstat`; the parser should be conservative and skip rows it
  cannot interpret rather than writing incorrect counts.
- DELTAS refresh is best-effort by design; failures must preserve existing DELTAS and not block the commit workflow.
- This task spans the core repo and the `retired Mercurial plugin` plugin repo. Avoid modifying generated skill files or CLI
  contracts; this change should stay within VCS provider behavior and tests.
