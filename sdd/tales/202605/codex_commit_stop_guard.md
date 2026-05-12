---
create_time: 2026-05-11 22:57:22
status: done
prompt: sdd/prompts/202605/codex_commit_stop_guard.md
---
# Codex Commit Stop Guard Plan

## Problem

The recently committed `sdd/tales/202605/codex_phase_commit_fallback.md` artifact correctly identifies that
SASE-launched Codex phase agents can finish with uncommitted changes because the Codex CLI `Stop` hook is not a reliable
delivery boundary for `codex exec`. The committed artifact is only an SDD prompt/plan commit, not an implementation.

The artifact's diagnosis is incomplete in one important way. The live `~/.sase_commit_stop_hook.jsonl` log shows both
failure modes:

- Some Codex phase agents that left dirty workspaces have no corresponding `script_start` entry, so the native Codex
  hook did not run at all.
- Other Codex runs did emit `block_emitted`, yet the workspace was still dirty afterward. In those cases the existing
  dedup marker only proves that a warning was emitted once; it does not prove that the agent committed the changes.

The proposed artifact design says to skip the fallback whenever `/tmp/sase_commit_hook_done_<session_id>` exists. That
would preserve the second failure mode. The real invariant should be: after a successful SASE-managed Codex invocation,
if the worktree is still dirty and the commit hook is enabled, Codex gets one more in-band commit instruction before
SASE records the agent as complete.

## Goal

Make SASE-launched Codex agents get a reliable, in-band commit-stop follow-up when they finish successfully with local
changes, whether the native Codex `Stop` hook was missed or merely failed to result in a commit.

Keep the fix narrow:

- Do not change Claude or Gemini behavior.
- Do not make the commit hook loop indefinitely.
- Do not change bead lifecycle semantics except through the existing commit instruction text.
- Reuse the existing stop-hook message construction so the native and fallback paths stay in sync.

## Design

### Hook Helper Surface

Extend `src/sase/scripts/sase_commit_stop_hook.py` with small reusable helpers rather than duplicating logic in the
Codex provider:

- A marker-path helper that computes the existing native hook marker from a session id.
- A commit-details helper that returns the changed-file list plus the exact instruction text currently emitted by the
  hook.
- Public names for helpers that production code imports from outside the script module. Keep existing private wrappers
  where tests or existing code already use them.

This avoids a provider-local copy of VCS detection, bead-close wording, PR naming instructions, and commit-method
wording.

### Codex Provider Fallback

Add a private fallback step in `src/sase/llm_provider/codex.py` after the normal subprocess turn succeeds and after user
interrupt handling has settled.

The fallback should:

1. Return immediately when `SASE_DISABLE_COMMIT_STOP_HOOK` is set.
2. Resolve the same SASE session id used by the hook where possible, primarily from `SASE_AGENT_TIMESTAMP`.
3. Check the current project directory for uncommitted changes using the stop-hook helper.
4. Return immediately if the worktree is clean.
5. Use a separate provider fallback marker, such as `sase_codex_commit_fallback_done_<session_id>`, to ensure SASE runs
   at most one managed fallback per provider invocation/session.
6. Do not treat the native hook marker as a skip condition. Instead log whether it existed. If the final worktree is
   still dirty, the native marker means the prior warning was insufficient, not that the state is safe.
7. Touch the native hook marker before the fallback subprocess when it was absent, so the second Codex subprocess does
   not also trigger the external hook and produce duplicate commit prompts.
8. Run exactly one additional Codex `exec` turn with:
   - the original prompt,
   - the accumulated response under `--- Work So Far ---`,
   - the exact commit-stop details from the hook under a clear final instruction.
9. Append the fallback response to the returned `InvokeResult` and return unconditionally. If the worktree remains
   dirty, SASE should not chase the agent forever.
10. Log fallback decisions to `~/.sase_commit_stop_hook.jsonl` with enough fields to distinguish clean skip, disabled
    skip, fallback emitted, native marker present, and one-shot skip.

### Tests

Add focused unit coverage in `tests/test_llm_provider_codex.py` and keep hook helper coverage in
`tests/test_commit_stop_hook.py`.

Important cases:

- Clean worktree: one subprocess invocation, no fallback.
- Dirty worktree with no native marker: two invocations; second prompt contains the changed files and
  `/sase_git_commit`; both native and fallback markers are created.
- Dirty worktree with native marker already present: still two invocations, because final dirty state matters; no
  duplicate native marker assumptions.
- Dirty worktree with fallback marker already present: one invocation.
- `SASE_DISABLE_COMMIT_STOP_HOOK=1`: one invocation even when dirty.
- Bead id propagation: with `SASE_BEAD_ID=sase-31.2`, the fallback prompt includes the existing bead-close instruction.
- One-shot behavior: if the mocked second turn leaves the worktree dirty, the provider still returns after the second
  invocation.
- Helper contract: public helper output remains equivalent to the existing private hook message builders.

## Validation

Run:

```bash
just install
pytest tests/test_llm_provider_codex.py tests/test_commit_stop_hook.py -x
just check
```

If `just check` fails in the known unrelated notification-store or visual snapshot areas, capture the exact failure and
make sure the focused tests still pass.

## Artifact Follow-Up

After implementation, update the SDD artifact status for the Codex fallback tale to reflect the implemented behavior and
note the correction: native hook marker presence is diagnostic data, not a final-clean guarantee.
