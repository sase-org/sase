---
bead_id: sase-3a
create_time: 2026-05-13 14:14:10
status: done
prompt: sdd/prompts/202605/finish_sase_3a.md
---

# Finish sase-3a Verification Cleanup

## Context

The epic asks that every pyvision `--epic-symbol` suppression for `sase-3a` be removed after each symbol is remediated
by deletion, privatization, or a legitimate non-test `# pyvision:` pragma.

Verification found that all child beads are closed, but `_lint-pyvision` still contains duplicated suppressions for:

- `MultiAgentXPromptDepthError`
- `QueryErrorWire`

`QueryErrorWire` already has a non-test `# pyvision:` pragma for `sase-core`, so its suppressions are stale.
`MultiAgentXPromptDepthError` was restored as a public exception by a later fix and needs an explicit legitimate
public-use remediation or a compatible private API change.

## Plan

1. Resolve `MultiAgentXPromptDepthError` by choosing the least disruptive remediation supported by the current code and
   tests.
2. Remove all remaining `sase-3a(...)` `--epic-symbol` suppressions from `Justfile`.
3. Run focused checks for the touched multi-agent xprompt and query-wire behavior, then run `just pyvision`.
4. Update the epic plan frontmatter to `status: done` after verification.
5. Close bead `sase-3a`.
