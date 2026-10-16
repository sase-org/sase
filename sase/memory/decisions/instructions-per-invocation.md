---
keyword: Instructions Are Rendered Per Invocation And Delivered By Adapters
aliases:
  - instructions-per-invocation
  - explicit instruction delivery
  - instruction bundle delivery
summary:
  Each SASE root invocation gets one memory-built instruction bundle through an
  adapter-owned explicit channel, with SASE-owned native files suppressed.
metadata:
  status: superseded-in-part
  decided: 2026-10-14
  superseded_by: decisions/readable-agents-md
---

> _Superseded in part:_ the Cost clause's "until E4/E5" retirement of committed native
> files, and the "until E4" legacy status of agy, Qwen, and OpenCode, are retired. See
> [[decisions/readable-agents-md]]. The rest of this record stands.

**Claim.** Every SASE root agent invocation renders one frozen instruction bundle from
memory and, when the provider's sunset flag is on, delivers that bundle exactly once
through an adapter-owned explicit channel. SASE-owned native instruction files are
suppressed for that call. Claude helpers get a separate helper bundle. A resumed session
inherits its own snapshot. Without an active explicit delivery the adapter behaves as it
did after E1. Per [[decisions/rust-core-required]], sase-core owns the v2 manifest wire,
delivery slots, fallback block, and invariants; Python owns the delivery-plan model,
adapter argv, channel ids, and Markdown composition.

**Why.** R-delivery's verified bugs were double contract loads (Claude and Codex), a
home layer that never reached Grok or Muse, and Grok loading zero project files in
untrusted workspaces. The accepted architecture is the R-delivery requirement
adjustments this epic implements:

- **R1. Deliver, don't write.** SASE runs receive SASE-owned instructions only through
  each adapter's explicit channel. Repo-owned files still load natively.
- **R4. Render per provider invocation, not per workspace launch.** Rendering happens at
  the `_invoke.py` boundary and in finalizer follow-up re-invocations. One invocation
  gets one frozen render.
- **R6. Exactly-once delivery is a tested invariant.** The scoreboard and
  `instructions.conformance` assert that the bundle marker appears once and that no
  SASE-owned native full file loaded.
- **R9. Hard rules and reference triggers are unconditional.** Audience `when:` (E7) may
  add or drop optional density; it cannot hide the runtime contract.
- **Last-known-good at runtime (R-delivery bundle lifecycle).** A render, validation,
  oversize, or materialization failure falls back atomically to legacy native discovery
  for that invocation, with a deduplicated notification. The context is never empty.
- **Rust/Python split (R-delivery boundary).** Composition stays in Python until a
  non-Python front end needs to preview a render.

Rejected alternatives: writing instruction files into the workspace and gitignoring them
(fails Grok's trust and gitignore rules, and Codex cannot suppress a present project
`AGENTS.md` without `project_doc_max_bytes=0`); splitting Codex across a shadow
`AGENTS.md` plus developer instructions (two channels, two marker counts, no helper
gain); leaving Claude's bundle in a user-message `CLAUDE.md` (compaction can summarize
it, helpers do not inherit it, `--resume` is weaker than the system-prompt snapshot);
keeping provider-owned memory channels on in SASE runs (they vary by workspace and
memory review never sees them). Home-layer parity is in: every explicit provider gets
the same bundle, home included. Foreign memory is off when the provider flag is on
(Claude `autoMemoryEnabled: false`, Codex shadow home omits `memories/`, Grok
`GROK_MEMORY=0`). Per [[decisions/adapters-normalize-harnesses]], each adapter owns its
channel. Per [[decisions/helpers-return-roots-declare]] and
[[decisions/single-turn-agents]], helpers return results and never declare.

**Cost.** Four sunset flags (`claude_explicit_instructions`,
`codex_explicit_instructions`, `grok_explicit_instructions`,
`muse_explicit_instructions`) keep the Off branch reachable for at least seven days of
clean explicit-run readout and conformance on every execution host; rollback is
`sase flag disable` per provider. Claude's move to `--append-system-prompt-file` changes
where the model sees the contract (system prompt rather than a user-message file). Codex
caps the slot at 32 KiB and Grok at 120 KiB; oversize falls back to legacy. The
no-`artifacts_dir` path (TUI fix-hook) stays legacy. agy, Qwen, and OpenCode stay
declared `provider_legacy` until E4. Native files remain committed until E4/E5, so the
per-invocation fallback still depends on them.

**Reopens when.** A provider loses every explicit channel, or the conformance check can
no longer observe that provider's loaded context. Also reopens if an explicit channel
measurably raises that provider's explicit-run miss rate more than two points above the
pre-cutover baseline attached to epic `sase-1ko`, and disabling its flag restores the
baseline — then that provider returns to native-file delivery alone.
