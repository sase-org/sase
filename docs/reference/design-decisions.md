---
title: Design decisions
description: Why SASE works this way, generated from the decisions memory web.
---

<!-- generated, do not edit; source: sase/memory/decisions/*.md (tools/render_design_decisions; run just fix to regenerate) -->

# Design decisions

Why SASE works this way, generated from the
[decisions memory web](https://github.com/sase-org/sase/tree/master/sase/memory/decisions).
Each record states its claim, what it costs, and what would reopen it. Records are
sorted A–Z and each anchor matches its memory slug.

## A Gate Never Blocks An Agent {#gates-never-block}

_Status: accepted · Decided: 2026-08-27._

_Also known as: gates never block, gate shells, blocking gate wait._

Creating a gate from inside an agent ends that agent's turn; continuation is a gate
shell's follow-up, never a wait.

**Claim.** A gate an agent creates becomes a gate shell: a named, non-LLM member of that
agent's family that publishes the decision, outlives its creator, runs the commands the
reviewer selects, and hands their typed outcome to the next family member. Creating a
shell gate hands off and kills the creating agent's turn immediately after the
descriptor prints; continuation is always the gate shell's recorded follow-up, never the
creator waiting, polling, or blocking on a response.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/gates-never-block.md)

## Adapters Normalize Harnesses {#adapters-normalize-harnesses}

_Status: accepted · Decided: 2026-09-23._

_Also known as: adapter harness normalization, harness conformance._

Each provider adapter makes its CLI harness conform to the single-turn contract instead
of the host modeling private wait semantics.

**Claim.** Each provider adapter makes its CLI harness conform to the single-turn
contract. Where the CLI allows, it disables native background and wake primitives
mechanically. It tells the model the provider's real synchronous ceiling. Otherwise it
detects violations with a bounded guard and fails loudly. The host never models a
harness's private wait semantics.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/adapters-normalize-harnesses.md)

## Agents Are Single-Turn {#single-turn-agents}

_Status: accepted · Decided: 2026-08-15._

_Also known as: single turn, one-turn agent._

A SASE agent run is one provider turn; continuation is always mechanical, never a
promise to resume.

**Claim.** A SASE agent run is exactly one provider turn. Work that outlives the turn is
continued by a mechanism that terminates the runner and starts a successor —
`sase monitor`, `/sase_handoff`, `/sase_plan`, `/sase_questions` — never by the agent
waiting, sleeping, or scheduling its own wake-up.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/single-turn-agents.md)

## Agents-Sync Is Publish-Only, The Import Leg Is Deleted {#agents-sync-publish-only}

_Status: accepted · Decided: 2026-09-05._

_Also known as: import leg removed, agents-sync publish-only, no more agent import._

Epic sase-ws deleted the entire agents-sync import leg (v1, v2, and the ACE
incomplete-import UI); the module only publishes agent prompts/pages outward now, and
one explicit purge command is the sole supported operation on leftover imported local
state.

**Claim.** `src/sase/agents_sync/` no longer contains any import machinery: there is no
v1 or v2 importer, no incoming cache or detection, no registry import mutations, no
`sase agent names forget-import` / `retire-v1` command, and no ACE incomplete-import
visibility gates. The only surviving leg is publication — the prompt archive, agent and
family pages, provenance links, and Referenced By write-backs — unchanged by the epic.
Locally materialized state left over from imports that ran before the leg was deleted
(`origin: import_v1` / `import_v2` registry rows, imported artifacts, dismissed bundles,
import journals/staging, incoming cache payloads, receipts) is pure history now; the
only supported operation on it is `sase agent names purge-local-state` (dry-run by
default, `--apply` to mutate) plus the matching `check_local_import_state` doctor check
that reports what is still left.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/agents-sync-publish-only.md)

## Check-Full Is Explicit-Only {#check-full-is-explicit}

_Status: accepted · Decided: 2026-09-19._

_Also known as: agents run check not check-full, landing does not run check-full._

just check is the only agent-initiated verification recipe; just check-full runs only
when explicitly instructed, typically to repair a CI failure.

**Claim.** `just check` is the only verification recipe a SASE agent runs unless the
current prompt, the user, or the assigned bead explicitly names `just check-full`. Epic
landers follow the same rule and therefore no longer author `%q(w=2.0)`. A `just check`
pass with a `just check-full` failure is a test-infrastructure bug, out of scope for the
current agent; file it through `/sase_new_task` and do not take it as remaining product
or landing work. `just check` may still escalate internally to the full test suite; that
is rare by design and is not the agent choosing `just check-full`.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/check-full-is-explicit.md)

## CI Is Two-Speed {#ci-two-speed-split}

_Status: accepted · Decided: 2026-08-28._

_Also known as: Master Gate vs Full CI, two-speed CI, release gate split._

Master pushes run a per-SHA fast gate, while the exhaustive CI matrix runs off the push
path on a schedule and remains a release prerequisite through ci_watch freshness checks.

**Claim.** CI is no longer the thing that runs everything on every push. A push to
`master` runs `Master Gate` (`.github/workflows/master-gate.yml`): a per-SHA,
never-cancelled fast gate with the lint gate and eight deterministic shards of the whole
non-visual fast suite. The exhaustive lane moved to `Full CI`
(`.github/workflows/full.yml`), a scheduled caller of `ci.yml` that runs every two hours
off the push path. `ci_watch` gates release on both signals: `gating_workflows` proves
this commit's fast gate is green, and `heavy_max_age_hours` requires a recent green
`Full CI` run.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/ci-two-speed-split.md)

## Completion Is Host-Owned {#host-owned-completion}

_Status: accepted · Decided: 2026-08-21._

_Also known as: finalizer declaration, agents never commit._

An agent never creates commits, branches, or PRs; it submits a declaration and
host-owned finalizers act.

**Claim.** A turn completes when the host's selected finalizers are satisfied, not when
an agent says it is done. The agent submits one atomic, turn-bound declaration; bounded
providers execute and independently verify postconditions; refusal requires a reason and
normally fails the run. An agent never creates commits, branches, or PRs directly.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/host-owned-completion.md)

## Expensive Commands Are Recorded Before They Are Admitted {#record-before-admit}

_Status: superseded-in-part · Superseded by:
[Guarded Recipes Refuse Raw Agent Runs](#guarded-recipes),
[Explicit Handoff Fails Closed](#explicit-handoff-fails-closed)._

_Also known as: record before admit, record first, admit last, ToolRun ledger first._

The sase tool control plane lands its ToolRun record first; prediction and admission
only ever consume a corpus that already exists.

**Claim.** An expensive command becomes a named tool whose every run is durably recorded
— fingerprint, per-stage timings, host load samples — before anything predicts its
duration or prices its admission. The ToolRun ledger lands first, in a new per-machine
Rust-owned store with its own retention; prediction consumes the corpus only after weeks
of samples and stays advisory until backtested; admission consumes calibrated
prediction, never guesses. A ToolRun is a semantic record that delegates execution to an
existing executor (inline child, monitor, durable proc): recording adds no new
supervisor, and recording stays fail-open even where admission later becomes
fail-closed.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/record-before-admit.md)

## Explicit Handoff Fails Closed {#explicit-handoff-fails-closed}

_Status: accepted · Decided: 2026-09-26._

_Also known as: fail-closed explicit handoff, tool run -H fail closed._

Explicit sase tool run -H fails closed when its ToolRun reservation cannot commit;
foreground and monitor-start recording stay fail-open.

**Claim.** Explicit `sase tool run -H` is fail-closed: if the ToolRun reservation cannot
be committed, nothing starts and the command exits 1 naming the foreground form.
Foreground `sase tool run` stays fail-open, and a monitor start's reservation is
fail-open (the monitor id is already the durable handle, so it falls back to wrapped
execution with one reason line). Once a hand-off is accepted, later recording failures
(observe, sample, finish) stay fail-open and are reported as incomplete evidence, never
as a reason to replay. This narrows one clause of
[Expensive Commands Are Recorded Before They Are Admitted](#record-before-admit)
("recording stays fail-open") for explicit hand-offs only, alongside
[Guarded Recipes Refuse Raw Agent Runs](#guarded-recipes).

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/explicit-handoff-fails-closed.md)

## Global Install Is Human-Only {#global-install-is-human-only}

_Status: accepted · Decided: 2026-10-09._

_Also known as: global installers refuse in agents, install-dev human only,
SASE_GLOBAL_INSTALL_BYPASS._

just install and just install-dev refuse inside SASE agents and monitors unless
SASE_GLOBAL_INSTALL_BYPASS holds a reason; agents propose global reinstalls through
/sase_gate.

**Claim.** `just install` and `just install-dev` refuse inside SASE agents and monitors
(exit 2) unless `SASE_GLOBAL_INSTALL_BYPASS` holds a non-empty reason, and agents
propose global reinstalls through `/sase_gate`. When the bypass is used, the installer
prints a one-line note naming the reason. This pairs with
[Guarded Recipes Refuse Raw Agent Runs](#guarded-recipes): guarded-recipes routes agent
runs into recorded ToolRuns, while this guard protects the host those runs execute on.
Do not edit `guarded-recipes`; this record links it.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/global-install-is-human-only.md)

## Goal Ledger {#goal-ledger}

_Status: accepted · Decided: 2026-09-28._

_Also known as: goal store, goal events._

A goal is its own Rust-owned domain, not a bead type. State is immutable events plus
live markers through the hidden clone, with O(unsettled) hot reads and
shown-never-promised freshness.

**Claim.** A [Goal](glossary.md#goal) is its own Rust-owned domain, not a bead type.
State is immutable events plus live markers, written only through the hidden clone. Hot
reads are O(unsettled): settled history is never opened. Freshness is shown, never
promised. Drafts stay local until named.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/goal-ledger.md)

## Goals Host Binds {#goals-host-binds}

_Status: accepted · Decided: 2026-09-28._

_Also known as: goal binding, bound goal._

The host binds every LLM turn to exactly one goal before spawn; agents only name or
adopt their own draft and claim or keep open; only a human settles.

**Claim.** The host binds every LLM turn to exactly one goal before spawn. Agents only
name or adopt their own draft, and only claim or keep a goal open; settling a goal —
verifying, acknowledging, canceling, merging, or superseding it — is a human act. This
holds invariants only: it says who may move a goal, never how turns are stored, how
attention is scheduled, or what happens when binding fails.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/goals-host-binds.md)

## Guarded Recipes Refuse Raw Agent Runs {#guarded-recipes}

_Status: accepted · Decided: 2026-09-22._

_Also known as: guarded recipes, require tool run, recipe guard._

A SASE agent runs a guarded recipe only inside sase tool run for that project root, or
with an explicit bypass; the guard refuses anything else.

**Claim.** An agent runs a guarded recipe (`check` and `check-full` in v1; `test` and
`install` are never guarded) only from inside `sase tool run <that tool>` for _that_
project root, or with an explicit `SASE_TOOL_BYPASS=<reason>`. A dependency-free POSIX
`sh` script (`tools/require_tool_run`), wired as the first `just` dependency, enforces
the routing: it refuses anything else with the wrapped and bypass forms on stderr and
exit 2. The name _and_ root match is strict, and _recording_ stays fail-open — the guard
enforces routing, not recording success, so `SASE_TOOL_NAME` is exported whether or not
the run recorded. This supersedes in part the bypass clause of
[Expensive Commands Are Recorded Before They Are Admitted](#record-before-admit): bypass
is still explicit and measured, but it is no longer the only mechanism — the default raw
call is refused.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/guarded-recipes.md)

## Hold Admission Uses Pull Evaluation With Fail-Open TTL {#hold-pull-fail-open}

_Status: accepted · Decided: 2026-09-26._

_Also known as: pull hold evaluation, fail-open hold store, hold TTL default._

Holds are one durable record per armer evaluated by each candidate at admission (pull),
with optional TTL (default 2h, cap 12h), fail-open store reads, and release scoped to
the armer session or shell end.

**Claim.** An agent hold is one durable record per armer, evaluated by each candidate at
the admission boundaries it already passes through (pull), never by writing a blocking
dependency into another launch's marker. `ttl=` is optional with a bounded default
(`agent_hold_default_ttl`, `2h`) and a hard cap (`agent_hold_max_ttl`, `12h`). A broken
or unreadable hold store fails open: admission ignores it rather than stranding a
waiter. A hold releases on explicit release, when the armer's session settles (agent
armer) or shell exits, or at TTL expiry — and a settled armer's `future` rule expires
with its record, never blocking later arrivals vacuously. Running work is immune by
construction, since both enforcement points (runner-slot admission for agents,
eligibility transition for undispatched procs) are pre-run. Directive summary in
[[macros.md]]; full contract in `docs/macros.md` and `plan:202609/hold_directive.md`.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/hold-pull-fail-open.md)

## Instructions Are Rendered Per Invocation And Delivered By Adapters {#instructions-per-invocation}

_Status: accepted · Decided: 2026-10-14._

_Also known as: instructions-per-invocation, explicit instruction delivery, instruction
bundle delivery._

Each SASE root invocation gets one memory-built instruction bundle through an
adapter-owned explicit channel, with SASE-owned native files suppressed.

**Claim.** Every SASE root agent invocation renders one frozen instruction bundle from
memory and, when the provider's sunset flag is on, delivers that bundle exactly once
through an adapter-owned explicit channel. SASE-owned native instruction files are
suppressed for that call. Claude helpers get a separate helper bundle. A resumed session
inherits its own snapshot. Without an active explicit delivery the adapter behaves as it
did after E1. Per [The Rust Core Is Required](#rust-core-required), sase-core owns the
v2 manifest wire, delivery slots, fallback block, and invariants; Python owns the
delivery-plan model, adapter argv, channel ids, and Markdown composition.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/instructions-per-invocation.md)

## Legacy V1 Agent Transport Is Read-Only History, Not An Import Source {#v1-import-retired}

_Status: superseded · Decided: 2026-09-03 · Superseded by:
[Agents-Sync Is Publish-Only, The Import Leg Is Deleted](#agents-sync-publish-only)._

_Also known as: v1 import retirement, v1_import_retired flag, v1 sunset._

The legacy v1 agents-sync import leg is sunset behind v1_import_retired; v1 payloads
stay readable as v2-adoption matcher evidence but are never materialized as new imported
artifacts.

**Claim.** The v1 agents-sync import leg is gated behind the `v1_import_retired` sunset
flag (default on, bead `sase-wc`). The gate lives inside
`src/sase/agents_sync/bundles.py::integrate_foreign_bundles`, at the two points that
materialize a new or refreshed imported artifact from a foreign v1 bundle
(`_create_imported_artifact` / `_refresh_imported_artifact`). With the flag on, those
calls are replaced with a diagnostic and an `IntegrationCounts.v1_import_skipped` count;
`src/sase/agents_sync/incoming_integration.py` surfaces that as a `sunset_skipped`
`CachedIntegrationResult` disposition (cached path) or a skipped receipt write
(full-sync path), in both cases leaving the hood visibly pending rather than silently
vanishing. Capture/detection (`incoming_detection.py`) and the v1 group ownership
classification (owner-observed, self-owned-already-present) are untouched: they are
evidence reads, not imports, and the v2-adoption matcher (`v2_import_v1_adoption.py`)
still depends on already-imported v1 artifacts being readable.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/v1-import-retired.md)

## Machine Artifact-Link Writes Stay Off the Primary {#machine-link-writes-off-primary}

_Status: accepted · Decided: 2026-09-26._

_Also known as: machine link writes off primary, hidden clone machine write lane._

Machine artifact-link mutations never target the sidecar clones nested under a project's
primary checkout; the machine write lane is the hidden host-owned clone, and the primary
converges only through pull-based auto-sync.

**Claim.** SASE machine (background) artifact-link mutations never target the sidecar
clones nested under a project's primary (human) workspace checkout. The machine write
lane is the hidden host-owned clone at `~/.sase/projects/<key>/repos/<role>`
(`hidden_sidecar_clone_dir`), following the agents-sidecar precedent; the primary's
nested `repos/<role>` clones are human-owned and converge only through the existing
pull-based `sync_primary_sidecar_role` auto-sync. Epic plan:
`plan:202609/machine_link_mutations_off_primary.md`. Link-index publication flows
through [[sase_artifacts.md]].

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/machine-link-writes-off-primary.md)

## Memory Links Are Authored {#memory-links-are-authored}

_Status: accepted · Decided: 2026-08-30._

_Also known as: authored memory links, wiki-style memory links._

A memory file declares how its links are detected and rendered, and authors links inline
as `[[target]]` / `![[target]]`.

**Claim.** A memory file declares how its links are detected and rendered, and authors
links inline as `[[target]]` / `![[target]]`.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/memory-links-are-authored.md)

## Memory Webs {#memory-webs}

_Status: superseded-in-part · Decided: 2026-08-24 · Superseded by:
[Memory Webs Render In Their Own Section](#webs-render-in-their-own-section),
[Memory Links Are Authored](#memory-links-are-authored)._

_Also known as: memory strands, web-backed memory._

A keyed memory collection is a flat descriptor note plus a sibling strand directory,
addressed web:keyword.

**Claim.** A keyed memory collection is one flat descriptor note
(`sase/memory/<web>.md`) plus a sibling directory of independently addressable strands
(`sase/memory/<web>/<slug>.md`), read on demand as `sase memory read <web>:<keyword>`.
The descriptor's own body, not any strand body, participates in core or reference
rendering. [Memory Web](glossary.md#memory-web) and
[Memory Strand](glossary.md#memory-strand) name this same shape.

> _Partially superseded:_ the sentence above on core/reference rendering is retired by
> [Memory Webs Render In Their Own Section](#webs-render-in-their-own-section).

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/memory-webs.md)

## Memory Webs Render In Their Own Section {#webs-render-in-their-own-section}

_Status: accepted · Decided: 2026-08-30._

_Also known as: web kind decides placement, tier-free web descriptors._

A memory web's placement in generated agent instructions follows from its kind, not from
a `type:` declaration on its descriptor.

**Claim.** A memory web descriptor does not declare `type:` or `parent:`;
`sase memory init` ignores both if present and strips them on convergence. A web's kind
— not a rendering choice — decides its placement: every web descriptor renders as its
own subsection of a dedicated Memory Webs section in generated agent instructions,
between core memory and reference memory, and a strand body never inlines regardless of
the web's frontmatter.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/webs-render-in-their-own-section.md)

## Native Helpers Return; Only Roots Declare {#helpers-return-roots-declare}

_Status: accepted · Decided: 2026-10-06._

_Also known as: helpers-return-roots-declare, root-only declaration, helper guardrail._

Only the host-launched root agent submits final declarations and runs turn-ending
operations; native helpers and forks return their results to their parent.

**Claim.** Only the host-launched root SASE agent — the provider turn SASE launched —
submits the final declaration and runs turn-ending operations
(`sase final context|defer|prepare|submit`, the turn-ending CLI forms the root-only
skills run, and the root-only skills themselves). Native subagents and forked helpers
never declare; their final message is their result, returned to their parent. The
contract sentence saying so lives in the `## SASE Final Declaration` section of the
generated instruction files, and enforcement is mechanical where a provider allows it
(Claude's packaged helper template plus the PreToolUse guard); elsewhere the sentence is
the coverage.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/helpers-return-roots-declare.md)

## No Retrieval Mechanism Before Its Corpus {#corpus-before-mechanism}

_Status: accepted · Decided: 2026-07-13._

_Also known as: mechanism before corpus, corpus first._

SASE does not build memory retrieval or linking machinery ahead of a corpus that
demonstrably needs it.

**Claim.** SASE does not ship memory retrieval, linking, or recall machinery ahead of a
corpus that demonstrably needs it. Mechanism follows corpus; the corpus is the evidence
that the mechanism is the right shape.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/corpus-before-mechanism.md)

## Plugins May Mount Top-Level Commands {#plugin-commands}

_Also known as: plugin commands, sase_commands, command plugins._

Plugins may mount top-level `sase <name>` commands through `sase_commands`; listen's
standalone-only stance is superseded.

**Claim.** Plugins may mount top-level `sase <name>` commands through the
metadata-declared `sase_commands` entry-point group, with sase-listen's `sase listen` as
the first consumer. This supersedes the `plan:202610/sase_listen.md` stance that
sase-listen stays a standalone tool rather than a sase plugin: sase-listen keeps its
standalone `sase-listen` binary and never imports sase, and additionally ships
`sase listen` through the generic mechanism.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/plugin-commands.md)

## Projects Are Shown By Name, Never By Directory Key {#project-labels-never-keys}

_Status: accepted · Decided: 2026-10-11._

_Also known as: project display names, project key leak, project labels never keys._

Project surfaces show PROJECT_NAME through the display snapshot; the directory key and
spec filename are identity only, and long-lived processes revalidate at refresh
boundaries.

**Claim.** A project's human-facing label is `PROJECT_NAME` through the display
snapshot. The directory key and the `*.sase` filename are storage identity only,
appearing at most as labeled identity fields in project-admin output and in
machine-readable (JSON) output. Long-lived processes revalidate at worker or tick
boundaries through a ProjectSpec stat token, and lookups stay memory-only. Labels never
come from paths.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/project-labels-never-keys.md)

## Receipts Prove Before They Skip {#receipts-prove-before-they-skip}

_Status: accepted · Decided: 2026-09-26._

_Also known as: receipts are proof not reuse, no reuse without measured opportunity._

Verdict receipts are proof for host completion, never execution skip or reuse; reuse
waits for measured content-equivalent repeat opportunity plus a hermeticity proof.

**Claim.** A verdict [Receipt](glossary.md#receipt) proves that a named verification ran
with a trustworthy verdict on an exact fingerprint, so host-owned prepared completion
can consult it. It never skips, reuses, or redirects a `sase tool run`: every invocation
still executes its child. A later reuse program (E4b) reopens only after at least 2
h/week of content-equivalent covered repeats for one tool on one machine for two
consecutive weeks, plus a hermeticity proof — measured through `sase tool receipts`,
never asserted from a single audit.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/receipts-prove-before-they-skip.md)

## Size Aliases Descend The Effort Ladder {#size-alias-effort-ladder}

_Status: accepted · Decided: 2026-09-20._

_Also known as: size alias effort ladder, alias reasoning effort rule, alias provider
redundancy._

Built-in size aliases run a model at xhigh on its first appearance from @xlarge down and
one rung lower on each reappearance; every alias should span more than one provider.

**Claim.** Scanning the built-in size aliases from `@xlarge` down to `@xsmall`, an
appearance is a `|` pool member or the primary (first candidate) of an ordered `||`
fallback chain. Non-primary ordered-fallback candidates and `(A | B) || C` last-resort
tails do not consume a rung. A model's first appearance runs at `xhigh` and each later
appearance drops exactly one rung of `EFFORT_LEVELS_ORDERED`. When a newer model of the
same provider occupies the top aliases, the previous model continues that provider's
descent from the next remaining size instead of restarting at `xhigh`: Grok 4.7 takes
`@large` at `xhigh`, while Grok 4.6 takes `@medium` at `high` then `@small` at `medium`.
A model that would need a rung below the bottom of its provider's supported range does
not belong in that alias; swap in a different model rather than repeating or
floor-clamping a rung. That is why Gemini, not a fifth Grok rung, holds the `@xsmall`
slot. A provider that publishes no reasoning-effort mechanism and bakes effort into the
model slug (Antigravity today) expresses its rung by choosing the variant
(`agy/gemini-3.8-flash-high`) and carries no `@effort` suffix; attaching one raises
`LLMInvocationError` at invoke time, because an alias-supplied effort is explicit. Every
model alias should also reach more than one LLM provider, through a `|` pool, a `||`
ordered fallback, or a `(A | B) || C` last resort, whenever more than one provider can
serve that size.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/size-alias-effort-ladder.md)

## The Rust Core Is Required {#rust-core-required}

_Status: accepted · Decided: 2026-05-01._

_Also known as: no python fallback, rust core boundary._

Shared backend behavior lives in sase-core with no Python fallback and no env-var
backend switch.

**Claim.** Shared deterministic backend and domain behavior lives in `../sase-core` and
is consumed through the `sase_core_rs` PyO3 wheel. It is a hard runtime dependency: no
`SASE_CORE_BACKEND` switch, no dispatcher, no dual-run parity mode, and no Python
reimplementation of a ported operation.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/rust-core-required.md)

## Triage Annotates; It Never Changes an Exit Code {#triage-annotates-does-not-change-exit-codes}

_Status: accepted · Decided: 2026-09-25._

_Also known as: triage annotates, triage exit code._

KNOWN needs an independent witness; triage classifies failure evidence without changing
command outcomes.

**Claim.** Failure triage annotates each failed [Tool Run](glossary.md#tool-run) with
durable NEW, KNOWN, FLAKY, or UNKNOWN items and a verdict, but never changes its exit
code. KNOWN requires an independent witness; insufficient evidence is UNKNOWN. Agent
runs may continue past stages containing only KNOWN or FLAKY items, but
`run_silent --finish` still returns the first continued failure's code.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/triage-annotates-does-not-change-exit-codes.md)

## Verification Is Two-Speed {#two-speed-verification}

_Status: superseded · Decided: 2026-08-05 · Superseded by:
[Check-Full Is Explicit-Only](#check-full-is-explicit)._

_Also known as: check vs check-full, scoped tests._

just check is the agent default and just check-full gates landing, because host capacity
is the constraint, not test speed.

**Claim.** `just check` — every whole-repo lint gate plus a diff-scoped test lane
selected from a static import-graph closure — is the agent default. `just check-full` —
every gate plus the full suite — is reserved for landing, broadening changes, and CI,
and runs through a monitor rather than inline.

[Read the full record on GitHub.](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/two-speed-verification.md)
