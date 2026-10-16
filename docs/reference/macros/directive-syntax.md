---
title: Directive syntax and completion
description: Directive forms, completion behavior, and model and dispatch settings.
---

# Directive syntax and completion

This page documents directive syntax, completion, and model or dispatch settings.

## Directives

Directives are in-prompt tags with a `%` prefix that modify agent runner behavior. They
are extracted and stripped from the prompt before further processing.

<a id="supported-directives"></a>
Moved to [Directive syntax and completion](#supported-directives).
<a id="tab-directive"></a>
Moved to [Directive syntax and completion](#tab-directive).
<a id="directive-completion-matrix"></a>
Moved to [Directive syntax and completion](#directive-completion-matrix).
<a id="static-conditional-segments"></a>
Moved to [Directive syntax and completion](#static-conditional-segments).
<a id="typed-launch-units"></a>
Moved to [Directive syntax and completion](#typed-launch-units).
### Syntax

Directives use the same argument syntax as macro references:

```
%model:claude-sonnet         # Colon syntax
%model(claude-sonnet)        # Parenthesis syntax (single value only)
%model:`claude-sonnet-4`     # Backtick syntax (for values with special chars)
%model:codex/o3              # Provider/model syntax — switches both provider and model
%m:agy/gemini-3.7-flash-high # Provider/model value with a stable Antigravity slug
%model:opencode/anthropic/claude-sonnet-4-5 # Nested provider/model syntax
%model:muse/muse-spark-1.3   # Meta Muse Code — never auto-detected from PATH
%model:grok/grok-4.7         # xAI Grok Build — never auto-detected; also in alias selectors
%model:@fast                 # Configured/implicit model alias; Model shows ← @fast
%model(opus, medium=codex/gpt-6.1-sol) # This agent uses opus; medium follow-ups use Codex
%model(medium=@large) # Leave this agent on its normal launch model; route medium follow-ups through @large
%effort:xhigh                # Set the reasoning-effort level for this prompt
%e:xhigh                     # Same, using alias
%effort:%{medium | high | xhigh} # Fan out directive values
%model:opus@xhigh            # Model + reasoning-effort suffix (alias: %m:opus@xhigh)
%dispatch:apollo             # Launch on the enrolled machine alias "apollo"
%{%m:opus@xhigh | %m:sonnet@low} # Per-branch effort via fan-out
%id:reviewer               # Short-form
%i:reviewer                  # Same, using alias
%i(reviewer, session=parent)  # Attach parent--reviewer to parent's session
%i(@, session=parent)         # Attach the next free feedback/Q&A suffix
%id(worker, clan=research)   # Derive research.worker and join clan research
%id(!worker, clan=research)  # Same derived name, with forced reuse
%id(reviewer, tribe=review)  # Name reviewer and assign it to tribe @review
%id(tribe=review)            # Auto-name the agent and assign tribe @review
#tribe:review                # Built-in shorthand for %id(tribe=review)
%id                        # Bare — auto-generates a unique name
%id:!reviewer              # Force reuse by wiping the previous owner
%clan:research.{@1}          # Declare a keyed template clan; this member uses a full hood-qualified id
%c:research.{@1}             # Same, using alias
%id:research.{@1}.cdx        # Keyed template; same key resolves together across the dispatch
%id(image, clan=research.{@1}) # Join the same keyed clan and derive research.{@1}.image
%id:outer.{@shared!}.lead    # Already-qualified key; share deliberately across nested swarms
%clan(research, tribe=review) # Declare a new clan in tribe @review
%clan(research, summary="Audit the authentication boundary") # Store a launch-time clan description
%clan(research, summary_script=./describe-clan) # Generate that description with an executable
%clan(research, summary_script=[[sase_clan_summary_plan "plans/research plan.md"]]) # Pass quoted script argv
%clan:research:: Audit the authentication boundary. # Text block; ends at the next top-level % or # line
%wait:agent1                 # Wait for agent1
%w:agent2                    # Wait for agent2 (alias)
%wait                        # Bare — waits for the most recently named agent
%wait:agent1,agent2          # Multi-value: equivalent to two separate %wait: lines
%wait(agent1, agent2)        # Same, paren form
%wait(agent=agent1)          # Named form of an ordinary agent wait
%wait:@review                # Wait for the next completed @review agent or clan
%wait(bead=<open-bead-id>)        # Wait for a bead in this project to close
%wait(hood=research)         # Wait for every current member of one hood
%wait(agent1, bead=<open-bead-id>, hood=research) # Require every condition
%wait(planner, for_epic=true)  # Same as %wait(planner); agent waits follow launched epics by default
%wait(planner, for_epic=false) # Release when planner finishes, even if it launched an epic
%wait(time=5m)               # Wait for 5 minutes before starting
%wait(time=1h30m)            # Wait for 1 hour 30 minutes
%wait(time=90s)              # Wait for 90 seconds
%wait(time=1430)             # Wait until 14:30 today (wraps to tomorrow if past)
%wait(time=260415/0900)      # Wait until 2026-04-15 at 09:00
%wait(agent1, time=5m)       # Wait for agent1, then a 5-minute floor
%queue:3                     # Use a per-launch capacity budget of 3
%q:3                         # Same, using alias
%queue(capacity=3)           # Same, named form
%q:1.5x                      # Use 1.5 × the effective capacity budget
%q(1.5x, w=0.25)             # Multiplier capacity with a quarter-unit claim
%queue(capacity=1)           # Run-alone barrier for a default-weight launch
%queue(priority=1)           # Join the runner queue ahead of larger priorities
%q(p=1)                      # Same, using the p= alias for priority=
%queue(weight=0.25)          # Claim one quarter runner-capacity unit
%q(w=2)                      # Same field using the w= alias; this claims two units
%queue(capacity=5, priority=20, weight=2) # Capacity, priority, and weight together
%wait(agent1, time=5m) %queue(capacity=1) # Dependencies, then time floor, then capacity budget
#t:5m                        # Shorthand for %wait(time=5m)
%hold:planner                # Name selector for an admission hold
%hold:planner,reviewer       # Colon list of name selectors
%hold:@nightly               # Tribe selector (positional @)
%hold(pending)               # Freeze the WAITING/QUEUED agents in scope
%hold(future)                # Fence launches submitted after the hold
%hold(hood=research)          # Hood selector
%hold(tribe=nightly)         # Tribe selector, keyword form
%hold(pending, future, ttl=90m, scope=host) # Widest form, explicit in the text
%repeat:3                    # Run the prompt 3 times
%r:5                         # Same, using alias
%{#review | #test}           # Brace shorthand: branches split on top-level `|`
%alt(#review,#test)          # Long form: same two variants, comma-separated
%(#review,#test)             # Parenthesized shorthand for the same two branches
%{sec=#review | perf=#test}  # Named branches become child name suffixes
%{extra instructions}        # Single branch: split into with/without variants
%auto                        # Auto-resolve plan, epic, and question gates using the default
%a                           # Same, using alias
%auto:plan                   # Auto-approve tale plans only; epic plans wait for review
%auto:tale                   # Same as :plan: auto-approve tale plans only
%auto:epic                   # Auto-approve epic plans only; tale plans wait for review
%auto:manual                 # Manual: auto off, exactly as if no %auto were present
%auto:off                    # Same as :manual
```

Model names containing spaces or parentheses must use the quoted parenthesis form (for
example, `%m("provider/Model Name (Variant)")`); colon syntax cannot express those
values.

The `%clan` directive and the `clan=` keyword on `%id` request execution-neutral
membership in a rootless parallel agent clan. Adding membership does not change the
model, waits, fan-out, spawn order, VCS/project context, or workspace behavior; it only
adds clan metadata and strips the directive before model execution. The clan name is a
reserved container, never an agent. `%clan` is a create-only declaration, requires an
explicitly hood-qualified member name, and may appear for a resolved clan in only one
prompt per launch. It errors if that clan already exists. Use
`%clan(<name>, tribe=<tribe>)` to assign one authoritative tribe to the generation.
Every other member uses `%id(<id>, clan=<clan>)`, which derives `<clan>.<id>` and joins
the newest generation or creates the clan implicitly without a tribe. The join form
cannot be combined with `%clan`; joining a clan also joins its tribe. A member segment
may fan out, and identical raw clan templates in one batch resolve to the same
generation. See [Agent Clans, Sessions, and Tribes](../agents/index.md) for the full
launch, wait, display, and cleanup contract.

The declaring `%clan` can also attach one launch-time description with `summary=`,
`summary_script=`, or the `%clan...::` text-block shorthand. These forms are mutually
exclusive, and clan joiners cannot replace the description. The `::` form requires a
following space or end of line and captures up to the next top-level line beginning with
a `%` directive or `#` reference. The captured text becomes metadata rather than member
instructions; use the explicit `summary=` form when the work prompt follows immediately.
Script-backed summaries may run synchronously during directive extraction and again
after the primary workspace, sidecars, and linked repositories are prepared. Both
attempts share the same 20-second, non-fatal contract and clan/epic environment; the
last successful non-empty output wins. Scripts must be read-only and idempotent because
runner re-exec can repeat them. `summary_script=` may contain shell-style quoted argv
(without invoking a shell), and `sase_clan_summary_plan PLAN_REF` renders a valid tale
or epic with the shared PLAN-lane layout; without `PLAN_REF`, it uses
`SASE_EPIC_PLAN_REF`. Scripts inherit the environment available to each attempt,
including epic `SASE_EPIC_PLAN_REF`, `SASE_EPIC_PLAN_SNAPSHOT`, `SASE_EPIC_BEAD_ID`,
`SASE_PHASE_BEAD_ID`, and `SASE_EPIC_CLAN_TRIBE`, while SASE overrides the clan identity
variables. The snapshot is an absolute project-scoped best-effort copy that the built-in
epic summary script uses as a guaranteed-local fallback after the normal checkout
candidates; the original reference remains authoritative for display and metadata. See
[Launch-time clan summaries](../agents/agent-clans.md#launch-time-clan-summaries) for the
complete ordering, execution, and persistence details. Re-creating a clan with a bare
`%clan(<name>)` or a generation-creating `%id(<id>, clan=<name>)` inherits the
remembered tribe and re-runs the remembered summary script (falling back to the
remembered text) when no explicit values are given.

The `%model` directive also supports automatic provider resolution: known model names
(e.g., `opus`, `o3`, `qwen3.6-plus`, `muse-spark-1.3`) are automatically mapped to their
provider. See [Per-Prompt Provider Switching](../providers/models.md#per-prompt-provider-switching) for
the full model-to-provider mapping. sase's TUI and the macro LSP complete `%model:` /
`%m:` values from the same model catalog used for provider resolution. The inserted
value is a canonical model name, a configured alias, or a qualified `provider/model`
value selected from a provider-scoped menu; provider short aliases are only
filter/display hints.

Model aliases are listed beneath the concrete model names. Each alias row shows its kind
(`role` or `custom`), the `PROVIDER(model)` target it currently resolves to — with an
` @ <effort>` suffix when the alias carries one — and its provenance (`configured`,
`implicit → @fallback`, `override`, plus a `· pool 2/3` chip for round-robin selectors).
Typing `@` right after the colon (`%m:@`) narrows the menu to aliases only; a bare
partial such as `me` still matches `@medium` through its bare name, but always after the
model rows. sase's TUI menu reflects active temporary alias overrides, while the LSP's
catalog is a launch-time snapshot that does not — restart the LSP to pick up config
changes, and use sase's TUI [Launch Control](../../ace.md#launch-control) (`,m`) to inspect
live override state.

<a id="equals-model-shortcuts"></a>
Moved to [Directive syntax and completion](#equals-model-shortcuts).
<a id="remote-dispatch"></a>
Moved to [Directive syntax and completion](#remote-dispatch).
<a id="launch-scoped-model-alias-overrides"></a>
Moved to [Directive syntax and completion](#launch-scoped-model-alias-overrides).
<a id="agent-names-waits-and-queue-admission"></a>
Moved to [Launch directives](directive-launch.md#agent-names-waits-and-queue-admission).
<a id="example"></a>
Moved to [Launch directives](directive-launch.md#example).
<a id="effort-directive"></a>
Moved to [Launch directives](directive-launch.md#effort-directive).
<a id="hide-directive"></a>
Moved to [Launch directives](directive-launch.md#hide-directive).
<a id="auto-directive"></a>
Moved to [Launch directives](directive-launch.md#auto-directive).
<a id="hold-directive"></a>
Moved to [Launch directives](directive-launch.md#hold-directive).
<a id="editor-review-marker"></a>
Moved to [Directive composition and fan-out](directive-composition.md#editor-review-marker).
<a id="plan-directive"></a>
Moved to [Directive composition and fan-out](directive-composition.md#plan-directive).
<a id="repeat-directive"></a>
<a id="stopping-a-repeat-chain-early-with-stop"></a>
Moved to [Directive composition and fan-out](directive-composition.md#repeat-directive).
<a id="alt-directive"></a>
<a id="where-opens"></a>
<a id="named-branches"></a>
<a id="single-branch-withwithout-split"></a>
<a id="cartesian-product"></a>
Moved to [Directive composition and fan-out](directive-composition.md#alt-directive).
<a id="multi-model-fan-out"></a>
Moved to [Directive composition and fan-out](directive-composition.md#multi-model-fan-out).
<a id="multi-value-directives"></a>
Moved to [Directive composition and fan-out](directive-composition.md#multi-value-directives).

## Supported Directives

See the generated [directive catalog](directives.md) for supported
names, aliases, syntax forms, argument summaries, and descriptions.

Agent identity uses `%id` or its `%i` alias. The retired `%name` and `%n` prompt
directives are not launch aliases. Using either as a top-level directive now raises a
migration error that points to `%id` / `%i` and, for clan membership, the
`%id(<id>, clan=<clan>)` form.

The retired `%tribe` and `%t` directives also raise a migration error. Use
`%id(<id>, tribe=<tribe>)`, `%id(tribe=<tribe>)` / `#tribe:<tribe>`, or
`%clan(<clan>, tribe=<tribe>)` according to the identity being tagged.

## Tab Directive

`%tab:<name>` or `%tab(<name>)` places the launch's presentation root on a named agent
tab. There is no `%tab` alias and no keywords; the directive is single-valued, so a
second `%tab` fails with `Duplicate directive '%tab' in prompt`, even when both values
agree. Fan-out branches may use different tabs (`%{%tab:a | %tab:b}`) because each
branch is its own unit.

`%tab:main` is the default tab and is stored as absent. `%tab:apollo` is an ordinary
named tab (machine aliases are ordinary names). Reserved names fail with the core
messages:

- `local`: `machine tabs are derived; omit %tab to land on the local machine tab`
- `all`: `there is no 'all' tab; use o in the grouping picker to see all tabs`

`%tab` cannot be combined with a stand-alone `%proc` unit
(`%tab cannot be used on a stand-alone %proc unit`). It may be combined with
`%dispatch`; the dispatch prompt still carries the tab. Session follow-ups and clan
joiners inherit the root/generation tab; an explicit `%tab` that differs from the
inherited tab fails and names `sase agent tab set`. The directive is stripped from the
model prompt; the raw prompt keeps it.

## Completion

The TUI and macro language server share the directive contract used by the parser. The
generated [directive catalog](directives.md) lists each directive's forms, aliases,
arguments, and purpose. Completion adds context-sensitive values such as configured
models, open beads, agent targets, and filesystem paths when those inventories are
available.

Completion filters out non-repeatable keywords already present and keywords that
conflict with a selected value; manually typed input still goes through normal
validation. Structured `%wait` keywords are available in parenthesized form, while
queue-admission fields belong to `%queue`. If a dynamic inventory cannot be read,
static directive names and values remain available, while dynamic suggestions may be
missing or stale.

## Static Conditional Segments

`%if(should_run=true|false)` is a static macro and multi-prompt inclusion directive. It
is not a typed-launch admission predicate and does not require a feature flag.

```text
Always launch this segment.
---
%if(should_run=false)
This whole segment is omitted before nested macros, name allocation, waits, preview,
approval, queue capacity, workspace selection, or dispatch see it.
---
%if(should_run=true)
This segment is kept, and only the `%if(...)` line is removed from the model prompt.
```

The only supported parenthesized keyword is `should_run=`. After ordinary template
rendering, its value must be exactly `true` or `false`, case-insensitive; this accepts
Jinja-rendered `True` and `False` but rejects empty strings, numbers, `null`, misspelled
values, and still-unrendered template expressions. Unknown keywords, duplicate keywords,
duplicate active `%if` directives in one segment, malformed parentheses, and mixed
static/script forms are hard errors. The whole expanded batch is validated before any
surviving segment launches, so a bad condition in a later segment cannot partially
dispatch an earlier one.

Static `%if` acts like literal deletion of the disabled segment and its separator. A
false first, middle, last, sole, or all-disabled batch is valid; an all-disabled batch
launches nothing rather than falling back to a blank agent. Bare `%wait` binds to the
previous surviving unit exactly as if the omitted block had never been written, and
surviving named waits keep their normal resolution behavior. Static conditions inside
inline code, fenced code, directive-owned code bodies, or `%macros_enabled:false`
regions are literal text.

Inside a macro body, the condition is evaluated after that body's Jinja rendering, so a
typed input can drive it:

```text
Draft the report.
---
%if(should_run={{ include_images }})
Generate the supporting images.
```

A Jinja filter can also drive the condition:
`%if(should_run={{ "grok" | provider_enabled }})` drops the segment whenever that
provider is disabled (see the `provider_disabled` / `provider_enabled` filters under
[Jinja2 Integration](templating.md#jinja2-integration)).

`provider_enabled` defaults to the `"any"` mode, so the bare filter drops the segment on
either a soft or a hard disable. A segment that pins an explicit provider model should
normally gate on `provider_enabled("hard")` instead: a soft disable only steers alias
and pool routing away from the provider and never refuses an explicit launch, while only
a hard disable trips the launch guard. Use `provider_disabled("soft")` when a segment
wants to react to a soft disable specifically (for example, to adjust prose rather than
drop the segment):

```text
Always launch this segment.
---
%if(should_run={{ "grok" | provider_enabled("hard") }})
This segment pins an explicit grok model, so it is dropped only on a hard disable.
```

In an [macro swarm](multi-agent-prompts.md#macro-swarms-library-defined-fan-out), a disabled segment is
dropped before any nested references in it expand. In an ordinary inline macro, a false
`%if` removes only that macro's own expansion; the prompt segment that references it
still launches with the rest of its text.

`%if(should_run=...)` cannot be combined with script admission syntax. For example,
`%if(should_run=false)::` and `%if("test -f pyproject.toml", should_run=false)` both
raise an error instead of dropping the segment silently. `%if:value` and `%if+` are not
static forms and raise an error; use `%if(should_run=...)` for static omission.

## Typed launch units

Script `%if::` and `%proc` forms are always available; the directives are never
forwarded to the model. Static `%if(should_run=true|false)` works the same way and is
resolved before typed launch planning. Directive names used as prose are left alone:
`stop un-admitted %if/%proc units` and line-leading text such as `%if is plain text` are
literal. A token becomes directive-like only when the name is followed by `(`, `:`, or
`+`; the bare code form must be immediately followed by `::`. Completion offers the
code-form rows and full Bash/Python snippet recipes, and the directive parser captures
these forms:

````text
%if::

```bash
test -f pyproject.toml
```
````

The parenthesized process forms accept either a positional Bash body or one named
`bash=` / `python=` body:

```text
%proc("just check")
```

```text
%proc(python="print('ready')", timeout="20m", label="Preflight")
```

The fenced form puts options before `::` and owns the fence that follows:

````text
%proc(timeout="20m", idle_timeout="5m", cwd="docs", workspace="true")::

```bash
just docs-check
```
````

The script-admission form `%if::` accepts exactly one closed `bash` or `python` fence
(intervening blank lines are allowed). `%proc` accepts one positional shell command, one
`bash=` or `python=` body, or the fenced `::` form; only one script `%if` and one
`%proc` may appear in a launch unit. Code bodies are opaque: `%` directives, `#`
references, YAML frontmatter, Jinja, and `$()` inside them are preserved literally. The
parser strips each directive and its body from the model prompt. Each planned fanout
slot is one launch unit. A slot containing `%proc` becomes a process unit and cannot
also contain agent prompt prose; `%id:<name>` gives that process unit a proc name.

Execution depends on who initiated the launch:

- User-initiated submissions from `sase run` and sase's TUI execute directly through
  durable typed admission. They freeze the same immutable typed plan and digest used
  after approval, then the admission coordinator waits for prerequisites, evaluates
  script `%if::`, and dispatches eligible units — agent units through the established
  agent launch path, and `%proc` units as native `named-proc` records with origin
  `prompt-proc`. A direct user submission does not create a LaunchApproval notification.
  If a wait remains unresolved, the `sase run` / sase's TUI launch proc can finish while
  a detached coordinator continues waiting; the coordinator writes a completion receipt
  and attempts a separate notification when admission settles.
- Agent-initiated launches still require LaunchApproval. Approval freezes the typed plan
  and digest before the gate is shown. After approval, the same coordinator admits
  units.

For script `%if::`, exit `0` makes the unit eligible, exit `1` skips it, and any other
exit, signal, timeout, cancellation, or execution failure records a condition error. For
a selected managed project, admission waits first, then briefly claims and prepares a
numbered operational workspace, runs the predicate from that checkout, and releases the
claim before any dispatch. The launch request's source cwd is not used as a project
fallback after lease, materialization, or preparation failure; those failures record a
condition error. Home/unmanaged conditions have no claimable numbered workspace and
retain the explicit source-cwd behavior. A false or erroneous condition allocates no
runner, agent identity, proc identity, or model request. The default timeout is 10
seconds. The predicate receives a sanitized environment, a private `HOME`, and a
versioned JSON context at `SASE_CONDITION_CONTEXT`, but this isolation is not a security
boundary: the predicate runs with the SASE process's filesystem and network permissions.

`%wait(agent=<name>)` is also an alternate spelling of an ordinary agent wait on direct
launch paths. Logical-unit and proc-wait admission are active only in the LaunchApproval
coordinator. There, bare `%wait` targets the preceding unit, `%wait(unit=unit-N)`
targets an exact logical unit, and `%wait(agent=<name>)` or `%wait(proc=<name-or-id>)`
targets a matching unit in the same plan when possible, otherwise an existing agent or
proc. A typed dependency is satisfied when the target settles, even if it was skipped or
failed; that outcome is available in the `%if::` context and does not automatically
cancel the dependent unit.

An eligible `%proc` unit dispatches natively once its waits and `%if::` pass, no active
[agent hold](directive-launch.md#hold-directive) matches it, and any authored queue fields pass the
runner-capacity check described below: the admission coordinator reserves a `named-proc`
(lifecycle `named-proc`, origin `prompt-proc`; SASE also reads the `proc-shell` lifecycle
spelling) and starts its detached supervisor. The supervisor then acquires an operational
workspace lease when `workspace` is true, materializes the approved source as a private
`0600` script, executes it by argv — `/bin/bash --noprofile --norc <script>` or the SASE
interpreter plus that script, never shell interpolation — and releases the lease through
the existing resumable settlement path on every terminal outcome. Execution and idle
timeouts begin when the child starts, not while waits, the condition, or the workspace
lease are pending. The child's environment inherits the detached supervisor's own
ordinary tool environment — `PATH`, `HOME`, locale, and toolchain configuration — rather
than a private hermetic one, so user-installed tools such as `just`, `uv`, and Cargo
resolve exactly as they do outside the proc. Parent agent, job, and artifact identity
are scrubbed from that inherited environment, along with any stale `SASE_PROC_*` sidecar
left over from an earlier proc, before the SASE interpreter directory is prefixed onto
`PATH` and only the current documented proc context (`SASE_PROC_ID`,
`SASE_PROC_LOG_PATH`, `SASE_PROC_SESSION_ID`, selected project, project file, and
workspace number) is added; the proc never sets `SASE_AGENT` or another agent-artifact
variable. The private script directory holds only the `0600` script and is not a
replacement user home, and this scrubbing is not a filesystem or network sandbox — the
child still runs with the supervisor's filesystem and network permissions. A stand-alone
`%proc` unit never allocates an agent runner slot, session, `done.json`, or finalizer
obligation.

A `%proc` unit may also carry `%queue` / `%q` fields:

```text
%q(1, priority=4, weight=0.25)
%proc("just check")
```

Queue fields make dispatch wait for a runner-capacity check that uses the same capacity
budget, priority, FIFO, and deference rules as an agent launch (see the `%queue` rules
under [Syntax](#syntax)). The check is not a claim: once dispatched, the proc holds no
runner capacity and never delays later launches. An omitted weight counts as `0` for the
check, so `%q:1` on its own waits while running work fills that budget. A weight that
can never fit keeps the unit pending instead of failing it. A proc without queue fields
skips the check entirely. While it waits, the unit has no Agents-tab row and is not
counted as `QUEUED`; for a direct submission, inspect its state in
`~/.sase/typed_launches/<request-id>/launch_admission/`, where `journal.jsonl` records
the capacity message and `receipt.json` summarizes unit outcomes.

In project context `workspace` defaults to `true` and an optional relative `cwd` is
resolved beneath the leased checkout; `workspace="false"` opts out and requires an
ordinary `cwd`. Outside project context no lease is taken and an explicit `cwd` is
required — `workspace="true"` without a selected project is a hard error. `%id:<name>` /
`%id(<name>)` becomes the proc's optional bare `proc_name` (validated independently of
the agent-session `--` naming convention); the canonical proc id is always allocated by
the proc store. Stop/kill is routed through the native proc-stop path and is responsive
in every phase — waiting, checking, acquiring the workspace, preparing the script,
running, and settling.

Typed admission preserves the complete identity binding for each agent unit, not only
the positional `%id` name: `%id` keywords (`clan=`, `session=`, `tribe=`, `bead=`), an
optional `%clan` declaration (`tribe=`, `summary=`, `summary_script=`), and force-reuse
`!` prefixes all survive planning. Dispatch reconstructs the equivalent `%id` and
`%clan` directives, then the existing model/effort/auto/final/hide/wait-runner
directives, and still omits admission-only `%if::` and logical dependency waits. Each
unit also retains its own workspace reference and `%dispatch` machine target. An
approved or coordinator-replayed remote unit is therefore dispatched to that machine
from its resolved project workspace instead of silently falling back to a local launch;
mixed local and remote units route independently.

Keyed `{@<id>}` agent-name markers resolve once across the complete expanded typed batch
before it is split into durable logical units. The concrete tokens are stored on the
immutable plan, so a delayed or restarted coordinator never reallocates the same key
independently per unit. Literal markers inside fenced code and macro-disabled regions
stay unresolved, matching ordinary launch-time keyed-marker rules.

Coordinator restarts replay the journal: a persisted terminal condition result is not
re-run, a reserved proc id is not duplicated, and agent/proc dispatch uses the stable
request fingerprint written at approval. CLI and sase's TUI notifications report the
same counts the receipt stores — total, eligible, launched, skipped, condition errors,
and launch errors.

Stand-alone named procs created this way appear in sase's TUI Agents tab as their own
top-level rows (never nested under an agent session), each marked with a `▣` glyph
alongside its proc name or short proc id, an optional `label`, a Bash/Python language
badge, the current phase/status, elapsed time, and project. Panel titles report a
separate `▣<count>` chip for stand-alone procs next to the ordinary agent-status chips;
a stand-alone proc never changes agent runner, unread, clan, or session counts.
Selecting a row opens a `NAMED PROC` detail with status/phase timeline,
project/workspace/cwd, language, code digest and safe preview, waits and condition
result, timeouts, and a bounded live-log tail — never the private script, the
`SASE_CONDITION_CONTEXT` file, or unbounded output. The same rows and details are
visible from the Procs pane.

## Equals model shortcuts

sase's TUI and the macro LSP also complete leading `=alias` and `==model` tokens into
canonical `%m:` expansions through shared Rust filters and edit plans. Typing `=` in an
macro-aware editor is an LSP completion trigger; manual completion works in the same
valid equals token. sase's TUI-only `ace.prompt_completion.auto_directive_menu` setting
does not change an editor client's trigger policy.

A marker is recognized only at prompt offset zero, at the start of a logical line, or
immediately after an ASCII space, with the caret after the equals marker. Escaped or
embedded equals signs, Markdown-style `=text=` / `==text==` marker pairs, paths, inline
and fenced code, disabled prompt regions, frontmatter, Jinja, placeholders, and
directive-owned input are excluded, matching sase's TUI. The old `*alias` and `**model`
spellings are ordinary prompt text. The `=alias` shortcut lists only effective built-in,
plugin, and user aliases (`implicit_alias` and `user_alias`) from the same catalog
`%model:` uses, in catalog order, with case-insensitive prefix matching. The `==model`
shortcut lists concrete model rows only, including provider-qualified matches such as
`==claude/fa`.

Accepting a row such as `@large` replaces the whole live `=query` token, including text
to the right of a mid-token caret, with `%m:@large`. Accepting a concrete model such as
`gpt-6.1-sol` replaces the whole live `==query` token with `%m:gpt-6.1-sol`. At prompt
or line end the expansion appends one ASCII space; before a tab it appends none; before
an existing ASCII space it preserves the rest of that whitespace run and leaves the
caret after the first space. When the trigger's `---` segment already holds a standalone
`%model`/`%m` directive, accepting instead deletes the shortcut token and rewrites the
earliest such directive in place with the selected value, removing any further
standalone model directives in the segment so exactly one remains; the caret lands at
the end of the rewritten directive. Directives inside alternation bodies (`%alt(...)`,
`%(...)`, `%{...}`), other `---` segments, and literal/definition regions are never
targets, and a trigger inside an alternation expands at its own token without touching
sibling branches or outside text. A valid shortcut with no matching rows returns an
empty shortcut list rather than unrelated completion. Unaccepted equals text has no
launch-time meaning.

The LSP reads the launcher-materialized catalog snapshot, so restart the editor session
after alias or provider config changes. sase's TUI live prompt bar can additionally
overlay temporary alias overrides for `=alias`; see sase's TUI
[model shortcut](../../ace.md#prompt-input-widget) and the
[editor integration](../../editor.md#equals-model-shortcuts) notes.

Provider rows such as `claude/` and `opencode/` are listed after model and alias rows in
the broad `%model:` menu. Accepting one drills into that provider and reopens completion
for qualified values such as `claude/opus`; typing the slash directly behaves the same.
The provider scope splits only on the first slash, so `%m:opencode/anthropic/` narrows
OpenCode's nested `anthropic/...` model names. Hidden providers stay out of completion
menus even though their explicit `provider/model` values remain routable.

When the final `%model` value was written as `@<alias>` — including a macro-expanded
reference such as `%model:@#agy_flash` — SASE records the expanded bare alias name in
`agent_meta.json` and renders it after the resolved model as `← @<alias>`. Concrete
values such as `%model:claude/opus` and literal values such as ``%model:`@text``` do not
get this chip. The chip is the alias named at launch, not the alias's current target.

## Remote Dispatch

`%dispatch:<alias>` and `%dispatch(<alias>)` route one launch to an enrolled,
non-quarantined remote machine. The directive accepts exactly one machine alias, has no
short alias, and may appear only once. `local` is reserved: omit `%dispatch` for an
ordinary local launch.

The source strips only `%dispatch`; the target receives and processes the remaining
prompt and launch directives. Launch requests do not forward `SASE_INSTRUCTIONS_FILE`.
The target renders instruction bundles with its own installed code; no instruction bytes
cross the wire. V1 remote launch cannot be combined with `%wait`, `%queue`, `%clan`, or
an active `%hold`, and it rejects local-only run payloads such as resolved launch units,
collected inputs, attachments, files, and images. The remaining prompt must be
non-empty.

Project context must be reproducible on the target. A trusted launch integration can
provide a Patch reference or explicit revision in the durable request payload; writing a
Patch or macro reference in the prompt does not supply that source-side evidence.
Without payload evidence, including for an ordinary `sase run`, the source directory
must be a clean Git checkout whose current branch has an upstream and whose `HEAD` is
not ahead of it. Dispatch requests are durable and idempotent; if acceptance is
uncertain, retrying the same request does not intentionally create a second remote
launch.

sase's TUI and the macro LSP complete configured machine aliases after `%dispatch:`. See
the [Remote Dispatch Runbook](../../remote_dispatch.md) for gateway setup, enrollment, status,
and remote-agent controls.

## Launch-Scoped Model Alias Overrides

The parenthesized `%model` form accepts keyword arguments that temporarily replace model
aliases for one launch lineage:

```text
%model(opus, medium=codex/gpt-6.1-sol, small=@xsmall)
%model(xsmall=@small, medium=@large@high)
%model(large=@xlarge, xlarge=codex/gpt-6.1-sol@max)
```

The optional positional value selects the current agent's model. Each `alias=value`
entry changes how that bare alias resolves — including for the current agent itself:
without a positional value, the agent falls through to `llm_provider.default_model`
(shipped as `@large`), so a `large=...` entry in the map reaches that launch too, on top
of any phase or task route derived from the `large` size. `%model(...)` keys must be
alias names; it cannot key on `default_model`, `epic_lander_model`,
`big_epic_lander_model`, or any other retired role name — set those scalar fields under
`llm_provider` directly instead. The size-specific worker routes use the five built-in
size aliases directly:

Phase and task workers route through the size alias that matches their size. See
[Role Aliases for Delegated Work](../providers/models.md#role-aliases-for-delegated-work)
for the routing rules and
[Implicit role aliases](../providers/models.md#implicit-role-aliases) for shipped
defaults. Tasks without stored size metadata use the `small` route.

Keys must be known builtin or custom alias names without `@`; values may be concrete
models, `provider/model` targets, quoted targets, macro references, or another alias
with `@`. A trailing reasoning-effort suffix is supported on a single-target value,
including an alias reference such as `@large@high`.

"Launch-scoped" describes persistence, not every subprocess the agent starts. SASE
records the map in agent metadata and carries it through its plan/coder follow-up path.
An explicit `%id(suffix, session=parent)` attachment inherits the parent's map when its
prompt supplies no alias keywords; a prompt with its own keywords uses that new map.
Ordinary nested launches do not inherit the map. This lineage often overlaps an
[Agent Session](../agents/index.md), but the terms are not interchangeable.

At each alias hop a launch-scoped value wins over a machine-wide temporary override and
the configured or implicit alias value.

The launch preview shows the resulting map before approval. Invalid alias names, missing
values, duplicate keys, self-references, and ambiguous bare alias values fail with a
directive error. Use `@medium`, not `medium`, when the value should reference another
alias.

A `%model` value may carry a trailing `@<effort>` reasoning-effort suffix (e.g.
`%model:opus@xhigh`); the effort is split off the clean model and behaves exactly like a
standalone `%effort` directive. See the [Effort Directive](directive-launch.md#effort-directive) below.

## Related

- [Directive catalog](directives.md)
- [Launch directives](directive-launch.md)
