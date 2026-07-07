---
create_time: 2026-07-07 15:24:31
status: done
---
# Plan: Complete sase-5h Verification Gaps and Close the Epic

## Context

Epic `sase-5h` ("VCS-Agnostic Repo Completion for `#gh` Refs", plan file
`sdd/epics/202607/vcs_repo_slash_completion.md`) has all six phase beads closed. A full completion audit was performed
against the epic plan across all four repos (sase, sase-github, sase-core, sase-nvim):

- **Phases 1–5 and the main-repo Phase 6 docs are verified complete.** All landed commits were read against the plan's
  Detailed Design; `just check` passes in sase; the full sase-github pytest suite passes; `cargo fmt --check` and
  `cargo test -p sase_core -p sase_xprompt_lsp` pass in sase-core; the Python↔Rust golden-vector tables were compared
  entry-by-entry and are byte-identical for all nine shared vectors (the tenth Rust-only vector is the intentional
  document-final-newline spacing accommodation from the Phase 6 fix).
- **Three test gaps remain** against the letter of the epic plan. One is a plan-explicit requirement (sase-nvim); two
  are minor coverage nits in sase.

This plan closes those gaps, marks the epic plan file done, and closes the epic bead.

## Remaining Work

### Step 1 — sase-nvim: assert `/` is an advertised trigger character (plan-explicit gap)

The epic plan (section 9 and Phase 6) requires the Neovim smoke test to "assert `/` is an advertised trigger character".
`tests/lsp_vcs_repo_smoke.lua` never inspects `server_capabilities.completionProvider.triggerCharacters`, while its
sibling `tests/lsp_vcs_project_smoke.lua` has `assert_plus_trigger` for `+`.

- Open the `sase-nvim` linked repo with `sase workspace open -p sase-nvim -r "<reason>" <workspace_num>` (using the
  workspace number of the primary sase repo checkout).
- Add an `assert_slash_trigger(client_id)` helper to `tests/lsp_vcs_repo_smoke.lua`, mirroring the sibling's
  `assert_plus_trigger`, and call it right after `wait_for_client(client_id)` before the completion assertions.
- Verify by running the smoke test headless against a freshly built sibling LSP binary
  (`cargo build -p sase_xprompt_lsp` in the sase-core linked repo, then point `SASE_XPROMPT_LSP_CMD` at it):
  `nvim --headless -l tests/lsp_vcs_repo_smoke.lua`.
- Commit in sase-nvim.

### Step 2 — sase: two small test-coverage additions (letter-of-plan nits)

1. **Bridge error-status round-trip.** Phase 1 requires "bridge op stdin/stdout round-trip incl. error statuses", but
   `tests/test_editor_helpers.py` only drives the OK path (with `vcs_repo_catalog_response` mocked). Add a test that
   feeds a malformed request (e.g. bad `schema_version` or missing `workflow`) through
   `handle_editor_helper_bridge(... "vcs-repo-catalog" ...)` un-mocked and asserts exit code 2, an
   `editor helper bridge error:` message on stderr, and no stdout payload.
2. **Explicit dismiss test.** Phase 3's test list names "dismiss"; the backspace-past-`/` dismiss logic in
   `_file_completion_refresh.py` is only exercised implicitly. Add a widget test to
   `tests/ace/tui/widgets/test_vcs_repo_completion.py` that opens the repo menu, deletes back past the trigger `/`, and
   asserts the completion menu is dismissed (`_file_completion_active is False`).

Verify with `just check`, then commit in sase.

### Step 3 — Mark the epic plan file done

Add `status: done` to the frontmatter of `sdd/epics/202607/vcs_repo_slash_completion.md` (replacing the current
`status: wip`). Commit in sase (may be folded into Step 2's commit if convenient).

### Step 4 (final) — Close the epic bead

Close `sase-5h`. All six child beads are already closed and every phase is now verified complete, so the epic can be
closed:

```bash
sase bead close sase-5h
```

After the bead is closed, run `just pyvision` in sase to confirm no unused code was left behind (some symbols are only
reported once the epic is no longer open).

## Out of Scope

- Any behavior change to the completion feature itself — every gap above is test/metadata-only.
- The sase-github 403-rate-limit-vs-auth classification nuance and the untested generic `OSError → tool_missing` branch
  noted during the audit: both are benign observations, not plan requirements.
- Wiring sase-nvim smoke tests into CI (the repo has no test runner target by design; all sibling smoke tests are manual
  headless runs).
