---
create_time: 2026-05-13 00:29:15
status: done
prompt: sdd/prompts/202605/sase_3c_completion.md
---
Plan: Complete sase-3c verification and closure

Context: The sase-3c epic removed cross-workspace bead reads. Verification found one remaining slow-path resolver gap:
in version-controlled mode, `find_beads_location()` only checks `cwd/sdd/beads` before falling back to the primary
workspace, so commands run from a subdirectory inside a numbered checkout can resolve the primary checkout instead of
the current checkout.

Steps:

1. Patch `src/sase/bead/cli_common.py` so version-controlled bead resolution walks from the current directory up through
   ancestors to find the current checkout's `sdd/beads` before falling back to the primary workspace.

2. Add a focused regression test proving `sase bead` read commands launched from a subdirectory of a sibling checkout
   read that sibling checkout's store, not the primary store.

3. Run targeted bead tests covering CLI read resolution and workspace resolution.

4. Update the epic plan frontmatter status to `done`.

5. Close bead `sase-3c`.

6. After the epic is closed, run `just pyvision` if available, then report any residual findings.
