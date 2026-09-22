---
keyword: Guarded Recipes Refuse Raw Agent Runs
aliases: [guarded recipes, require tool run, recipe guard]
summary:
  A SASE agent runs a guarded recipe only inside sase tool run for that project root, or
  with an explicit bypass; the guard refuses anything else.
metadata:
  status: accepted
  decided: 2026-09-22
---

**Claim.** An agent runs a guarded recipe (`check` and `check-full` in v1; `test` and
`install` are never guarded) only from inside `sase tool run <that tool>` for _that_
project root, or with an explicit `SASE_TOOL_BYPASS=<reason>`. A dependency-free POSIX
`sh` script (`tools/require_tool_run`), wired as the first `just` dependency, enforces
the routing: it refuses anything else with the wrapped and bypass forms on stderr and
exit 2. The name _and_ root match is strict, and _recording_ stays fail-open — the guard
enforces routing, not recording success, so `SASE_TOOL_NAME` is exported whether or not
the run recorded. This supersedes in part the bypass clause of
[[decisions/record-before-admit]]: bypass is still explicit and measured, but it is no
longer the only mechanism — the default raw call is refused.

**Why.** Instruction-led adoption plateaued near 90% wrapped, and the remaining gap is
structural: E4 receipts, E6 forecasting, and E7 fail-closed admission all need "every
heavy agent run is a ToolRun" to hold by construction. Rejected alternatives: a `sase`
subcommand as the guard fails in exactly the states the override exists for (broken
`sase`) and taxes every human and CI run for logic that needs three environment
variables; a silent redirect inside `just` would need a public-stub/private-body split
with double-run hazards, and could one day hand a run to a monitor or return a cached
receipt and end the agent's turn unasked.

**Cost.** The guard is a guardrail against habit, not a security boundary
(`env -u SASE_AGENT` defeats it; the bypass is deliberately easier). Every human and CI
`just check` pays one dependency-free `sh` exec. Strict matching refuses
`-- sh -c 'just install && just check'` wrappers that a lenient match would accept,
trading convenience for the named identity history and fingerprints key on.

**Reopens when.** Bypass stays above a sustained rate that says the guard costs more
than it records, or any false refusal (a correctly routed run turned away) is observed.
