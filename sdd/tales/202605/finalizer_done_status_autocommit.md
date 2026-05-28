---
title: Finalizer auto-commit for SDD plan done status
create_time: 2026-05-28 09:05:44
status: done
prompt: sdd/prompts/202605/finalizer_done_status_autocommit.md
---

# Plan: Finalizer auto-commit for automatic SDD plan done status

## Goal

Prevent agent runs from failing when the only remaining dirty file is an SDD plan-like markdown artifact whose automatic
status update changed `status: wip` to `status: done`.

The finalizer should resolve that narrow case itself, without spending a follow-up LLM pass, and the resulting commit
message must include the appropriate `TYPE=sdd` tag.

## Current behavior

- `handle_sase_plan()` updates the active `SASE_PLAN` file with `sed -i 's/^status: wip$/status: done/'`.
- The provider-neutral commit finalizer currently only detects dirty state, asks the provider for up to
  `commit.finalizer.max_passes` follow-up turns, and fails if changes remain.
- In the observed failure, the finalizer ended with only `sdd/tales/202605/xprompt_frontmatter_xprompts.md` still dirty
  because the plan status line had already been changed to `done`.

## Design

Add a direct, fast auto-commit path inside the commit finalizer before it invokes a follow-up provider turn, and repeat
the same check after each follow-up pass before deciding whether another pass is required.

The auto-commit path should be deliberately narrow:

- It only applies when the dirty state contains exactly one dirty repo.
- That repo must be the main workspace repo, not a configured sibling repo.
- Git porcelain status must report exactly one changed path.
- The path must be a tracked markdown file under an SDD plan-like directory, initially `sdd/tales/`, `sdd/epics/`,
  `sdd/legends/`, or `sdd/myths/`.
- Comparing `HEAD:<path>` with the current worktree file must show exactly one changed line.
- That changed line must be in frontmatter and must be exactly `status: wip` in `HEAD` and `status: done` in the
  worktree.

If all checks pass, stage only that path and create a direct git commit with a focused message such as:

```text
chore: Mark SDD plan done

TYPE=sdd
```

Use the existing `apply_auto_commit_type_tag(..., "sdd")` helper to add the tag so commit-message tag formatting stays
consistent with existing SDD auto-commit code.

If any git command fails, treat the auto-commit attempt as a no-op and continue through the existing finalizer flow. Do
not mask broader dirty states, and do not auto-commit untracked, renamed, deleted, sibling, or multi-file changes.

## Implementation Steps

1. Add a small helper module or helper functions near `commit_finalizer_git.py` for status-only SDD plan detection and
   direct commit execution.
   - Keep subprocess timeouts short.
   - Avoid invoking `sase commit`, precommit hooks, or another provider turn for this narrow case.
   - Stage and commit only the single qualifying path.

2. Wire the helper into `run_commit_finalizer()`.
   - After initial dirty-state collection, try the auto-commit path before building a follow-up prompt.
   - After each provider follow-up and fresh dirty-state collection, try the same path before deciding whether the repo
     is clean or another pass is needed.
   - When the auto-commit succeeds and the repo is clean, write a normal `CommitFinalizerResult` with status
     `finalized`, reason like `auto_committed_done_plan_status`, and zero or current pass count as appropriate.

3. Add focused tests.
   - A dirty repo with only `sdd/tales/...md` changing frontmatter `status: wip` to `status: done` is auto-committed,
     the provider is not invoked, and the commit message contains `TYPE=sdd`.
   - A dirty repo with any additional file does not auto-commit and still invokes the provider path.
   - A dirty SDD markdown file whose changed line is not exactly the frontmatter status transition does not auto-commit.
   - A sibling repo status-only change does not auto-commit.

4. Run targeted tests first, then the repository check.
   - Targeted: commit-finalizer tests plus the new test module.
   - Required by repo instructions after file changes: run `just install`, then `just check`.

## Risks and Guardrails

- The biggest risk is accidentally committing user-authored SDD content. The exact one-line `HEAD` vs worktree
  comparison and frontmatter requirement keeps the blast radius small.
- Direct git commit bypasses normal `sase commit` tracking. That is intentional for this generated closeout status
  change; the commit is only for the SDD status update and carries `TYPE=sdd`.
- This should not replace the existing LLM-driven finalizer for normal dirty code, prompt, bead, or sibling changes.
