---
create_time: 2026-05-11 21:42:08
status: done
prompt: sdd/prompts/202605/sase_2z_completion.md
---
# Plan: Complete sase-2z Verification and Hardening

## Context

The `sase-2z` epic has three closed child beads and one open child bead: `sase-2z.4` ("Phase 4: Hardening, Docs, and
Live Smoke"). Source review found that the core tool behavior is implemented, but Phase 4 hardening still has two `gh`
boundary issues to address before the epic can be closed:

- `GhClient.default_branch()` decodes a `gh --jq` result as JSON, but `gh` emits raw text for that query.
- `GhClient` appends `--repo` to `gh api`, but this installed `gh` exposes no `--repo` flag for `api`; explicit repo
  selection must be handled without that flag.

## Implementation Steps

1. Update `tools/last_workflow_set_status` so default branch detection handles raw `gh --jq` text, and make `gh api`
   calls work for both current-directory repositories and explicit `--repo OWNER/REPO` values.
2. Add focused tests in `tests/test_last_workflow_set_status_cli.py` for raw default branch output and explicit-repo API
   endpoint construction.
3. Run targeted tests for the workflow status tool, then run the repo-required validation commands (`just install` if
   needed and `just check`).
4. Run the opt-in live smoke command when `gh auth status` is healthy:
   `tools/last_workflow_set_status --repo sase-org/sase --branch master --limit 50 --tail 20`.
5. Close child bead `sase-2z.4`.
6. Close epic bead `sase-2z`.
7. After the epic closes, run `just pyvision` and address any relevant unused code findings.
8. Update `sdd/epics/202605/last_workflow_set_status_tool.md` frontmatter so `status: done`.
