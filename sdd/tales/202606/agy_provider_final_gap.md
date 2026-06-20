---
title: Close agy provider MVP verification gap
bead_id: sase-50
create_time: 2026-06-19 21:48:43
status: done
prompt: sdd/prompts/202606/agy_provider_final_gap.md
---

# Close agy provider MVP verification gap

## Context

Verification of epic `sase-50` found that phases 2 through 7 are implemented and tested, but the Phase 2 handoff note
left one explicit gap for Phase 7: `agy --print` prompt transport sends the full prompt as one argv element, so very
large SASE prompts can fail with an opaque OS argument-size error. The current implementation documents that transport
but does not guard it.

## Plan

1. Add a conservative `AgyProvider` prompt-size guard before spawning `agy` so oversized `--print` prompts fail with an
   actionable SASE error that explains the upstream Antigravity CLI limitation.
2. Add unit coverage proving oversized prompts do not call `subprocess.Popen` and that the diagnostic mentions argv
   transport and the missing stdin/prompt-file contract.
3. Update `docs/llms.md` and the Phase 7 hardening note to record the guard as the resolution for the large-prompt
   transport gap.
4. Run focused tests for the `agy` provider and then `just install && just check`.
5. Close remaining open child bead `sase-50.1`, close epic bead `sase-50`, run `just pyvision` if available, and mark
   the epic plan frontmatter `status: done`.
