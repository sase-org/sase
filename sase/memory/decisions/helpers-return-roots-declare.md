---
keyword: Native Helpers Return; Only Roots Declare
aliases: [helpers-return-roots-declare, root-only declaration, helper guardrail]
summary:
  Only the host-launched root agent submits final declarations and runs turn-ending
  operations; native helpers and forks return their results to their parent.
metadata:
  status: accepted
  decided: 2026-10-06
---

**Claim.** Only the host-launched root SASE agent — the provider turn SASE launched —
submits the final declaration and runs turn-ending operations
(`sase final context|defer|prepare|submit`, the turn-ending CLI forms the root-only
skills run, and the root-only skills themselves). Native subagents and forked helpers
never declare; their final message is their result, returned to their parent. The
contract sentence saying so lives in the `## SASE Final Declaration` section of the
generated instruction files, and enforcement is mechanical where a provider allows it
(Claude's packaged helper template plus the PreToolUse guard); elsewhere the sentence is
the coverage.

**Why.** Helpers inherit the root's environment identity: `sase final` identifies the
turn from environment variables only, so the host cannot tell a helper's submit from the
root's. Over 30 days, 13–15 Claude helpers invoked `sase final`, and 2 submissions were
accepted for their parent's turn. General-purpose Claude helpers load the contract twice
and are told to "use `/sase_final`", while Explore helpers get no instructions at all.
Rejected alternatives: env-based helper identity (helpers inherit the env, so there is
nothing to distinguish); disabling native subagents (providers own that surface, and
helpers are useful when they stay in their lane); and a host-side caller check (no
reliable identity exists at the call site — Claude's `agent_id` hook field is the
closest thing and it is only visible inside the hook, which is why the guard lives
there). Per [[decisions/host-owned-completion]], completion stays host-owned; per
[[decisions/single-turn-agents]], a turn is one provider run; per
[[decisions/adapters-normalize-harnesses]], each adapter conforms its own harness.

**Cost.** Reliance on a hidden Claude flag (`--append-subagent-system-prompt-file`,
probed without an API call and omitted with a warning when unsupported), the fork result
from the live probes (depth-2 nested helpers carry `agent_id`, so the guard covers
forks), and text-only coverage for every other provider's helpers (Grok subagents get
nothing; the child channel is deferred).

**Reopens when.** A host-verifiable helper identity or a provider-native helper identity
appears — for example, the host minting per-turn credentials the guard can check, or a
provider exposing "this call came from a subagent" outside the hook payload.
