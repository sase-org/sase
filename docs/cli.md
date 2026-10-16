# CLI Reference

This page is a command index for the top-level `sase` CLI. It is meant for discovery and
routing: use it to find the surface that owns a workflow, then follow the links to the
detailed command, flag, or subsystem reference.

Compact `sase --help` lists only the common commands. Use `sase --full-help` (or `-H`)
to print every command, then this page to route from a command to its owner guide. This
page is a discovery index, not a dump of every flag. Compact help's one-line `agent`
blurb says "active and recent"; default `sase agent list` (and bare `sase agent`) is
running-only — add `-a` for recent DONE/FAILED.

When a plugin mounts commands, compact help adds a **Plugin commands** group after the
common commands. Each row is the command name, its one-line summary, and the
distribution that provides it. The group is left out when nothing is mounted. A plugin
that fails to load can still appear there with its distribution's summary, so being
listed does not prove that it can run. Load failures, name collisions, and shadowed
names appear on `sase --full-help` instead, each marked `⚠`, and that footer closes with
a pointer to `sase plugin list` and the Updates tab. See
[Command plugins](plugins.md#command-plugins).

Compact help's `memory` blurb still mentions reviewing proposals, but that CLI workflow
has been removed. Current memory commands inspect, read, initialize, and audit memory;
sase's TUI Memory panel can add/edit/delete flat notes and add/delete strands, while
existing strand bodies and web descriptors are edited in `$EDITOR`. Agents must route
all memory-file changes through `/sase_memory_write` first.

For exhaustive flags, options, and subcommands, see the generated
[CLI command groups](reference/cli/index.md).

The root `sase` command accepts leading global options before the subcommand:
`-f/--enable-feature` and `-F/--disable-feature` force a registered feature flag on or
off for that invocation and its children, and `-p/--print-command` prints a
shell-quoted, copyable `sase ...` header to stderr before running the command. The
printed invocation omits only the root print switch. See the
[configuration reference](configuration.md#feature_flags).

## Daily Operation

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase agent](reference/cli/agent.md), [sase chat](reference/cli/chat.md),
  [sase prompt](reference/cli/prompt.md), [sase stitch](reference/cli/stitch.md)
- [sase gate](reference/cli/gate.md), [sase autonomy](reference/cli/autonomy.md),
  [sase sudo](reference/cli/sudo.md), [sase notify](reference/cli/notify.md)
- [sase proc](reference/cli/proc.md), [sase repro](reference/cli/repro.md)
- [sase tui](reference/cli/tui.md), [sase service](reference/cli/service.md),
  [sase scheduler](reference/cli/scheduler.md),
  [sase screenshot](reference/cli/screenshot.md),
  [sase tmux-agent](reference/cli/tmux-agent.md), [sase run](reference/cli/run.md),
  [sase pager](reference/cli/pager.md)

Workflows: [TUI](ace.md), [Scheduler](axe.md), [Monitors](monitors.md),
[Prompt history](prompt.md), [VCS](vcs.md), [Notifications](notifications.md),
[Macros](macros.md).

`sase stitch list --origin ORIGIN` accepts `stitch`, `auto`, or `manual`; repeat the
flag to OR multiple origins. `sase stitch list --format json` includes the same
canonical value as each commit's `"origin"` field.

`sase run` launches detached background agents that appear in sase's TUI Agents tab. It
can start from prompt text, macro or workflow references, the editor, or the
prompt-history picker, and multi-prompt input expands into sequential background
launches. sase's TUI uses the same launch machinery when users start agents from the
TUI. When `sase run` is used from an interactive terminal (not from inside an agent or a
durable proc) and its [`%hold`](macros.md#hold-directive) preview is broad, it prints
the preview and asks `Arm this hold? [y/N]`; declining cancels the launch and exits `1`.
A host-scoped hold that includes `future` is always broad. A `pending` hold is broad
when its live capture exceeds `agent_hold_confirm_capture_threshold`, but that check
needs project context: typed launch plans can resolve it, while a plain project-scoped
`sase run` prompt currently cannot and therefore skips this confirmation. Once accepted,
the launch submission pre-arms the hold before admission can race ahead, then rebinds
ownership to the launched runner. Narrow and non-interactive holds use that same pre-arm
path without the extra prompt.

The short option `-n` is not one flag across commands: `sase agent kill -n NAME` and
`sase agent hold create -n NAME` are `--name` (for `kill` it is required; a bare name is
a usage error), `sase agent drain -n` and `sase agent restart -n` are `--dry-run` (the
agent name or provider is positional), and `sase monitor start -n` is `--next`.
Likewise, `sase agent wait -a` is `--all`: it snapshots the eligible agents running when
the wait starts, while `sase agent list -a` means include recent completed agents in a
list view. `sase agent hold create -p` is `--pending`, not `--project`.

### `sase autonomy`

Autonomy controls automatic resolution of plan and question gates. A fresh user launch
without `%auto` is manual; bare `%auto` selects `standard`. The `tale` and `epic`
profiles restrict which plan tier resolves automatically, while both still choose the
first option for each question. See the [profile matrix](macros.md#auto-directive).

```bash
sase autonomy list
sase autonomy show tale
sase autonomy explain --prompt '%auto:tale'
sase autonomy explain my-agent
sase autonomy explain --gate plan/REQUEST_ID
sase autonomy log my-agent --since 1h --kind plan --outcome auto
```

All four subcommands accept `-j/--json`; bare `sase autonomy` delegates to `list`.
`list` includes effective epic phase/land role assignments. `show PROFILE` accepts
`manual`, `standard`, `tale`, or `epic`. `explain` reads an agent's live record,
dry-runs prompt text with `-p/--prompt` (leaving `$(...)` unexpanded), or reads the
policy revision that decided a settled gate with `-g/--gate`. A gate can be named as
`KIND/REQUEST_ID` or by its gate-turn short ID, member name, or owning agent. `--prompt`
and `--gate` cannot be combined. Prediction does not launch work or answer a gate.

`log [AGENT]` reads host decisions newest first. `-k/--kind` accepts `plan`,
`epic_plan`, or `question`; `-o/--outcome` accepts `auto` or `ask`, and `-s/--since`
accepts a date or relative bound such as `1h`. Manual evaluations leave no log rows.
Launch, sudo, custom, and other privileged gates require human action regardless of
profile. The live TUI `A` toggle applies to the next gate and is inherited by later
successors; see [Auto-Approve Toggle](ace.md#auto-approve-toggle).

### `sase agent auto-restart`

The scheduler's recovery service classifies update-skew failures and can relaunch an
eligible agent once per lineage. Use `list` for pending claims, `list -a` for the full
ledger, `show TARGET` for one record's evidence, and `scan` for read-only historical
classification. `run NAME`, `run -a DIR`, or `run -p` invokes the healer; `resume`
clears a storm pause. The configuration switch is
[`agent_auto_restart.enabled`](configuration.md#agent_auto_restart).

A bare invocation delegates to `list`. `run --dry-run` can write recovery state for
existing stale claims, and a successful `run -j` exit does not guarantee a relaunch. See
[Agent Auto-Restart](agent_auto_restart.md#cli) for the options, output contracts, and
current probe/deferral limitation.

### `sase agent search`

`sase agent search [QUERY ...]` searches the historical agent catalog behind the Agents
tab Archive, rather than the live operational rows returned by `agent list`. Without an
`in:` token it keeps the current catalog behavior. Queries use `AND`, `OR`, `NOT`,
parentheses, free text, and the catalog's identity, lineage, lifecycle, time/runtime,
and artifact-link fields. For example:

```bash
sase agent search 'revivable:true AND project:sase AND role:code'
sase agent search 'provider:codex AND status:FAILED AND since:7d'
sase agent search 'linked:true AND relation:read'
sase agent search 'in:inbox AND status:FAILED'
sase agent search 'in:archive AND outcome:failed AND project:sase'
```

A bare search applies the default presentation scope: hidden rows and
`kind:workflow-child` rows are omitted unless the query explicitly asks for them. The
default cap is 40; `-l 0`, `--limit 0`, or `limit:all` removes it, and an explicit
`-l/--limit` overrides a `limit:` token inside the query. `-p/--project` accepts a
project key, alias, or display name. Options may appear before or after the query, and
`-j/--json` emits a stable array.

`in:inbox` keeps the catalog query path and restricts matches to non-dismissed rows.
`in:archive` searches hidden archive rows through the shared archive corpus; it supports
the archive profile fields `outcome`, `restorable`, `tab`, `tribe`, `clan_tribe`,
`linked`, `relation`, and `artifact`. Archive output is ordered by last activity, and
JSON contains the corpus's light derived rows. The token is host-owned, may appear once
at top level, and cannot be negated or appear inside `OR` or parentheses.

### `sase agent wait`

`sase agent wait NAME ...` resolves each target the same way `%wait` does: clan, then
agent session, then workflow, then exact agent name. A session target waits on the whole
session, including successors that appear after the wait begins. `sase agent wait -a`
waits for every eligible agent running at command start and deliberately does not absorb
later unrelated launches; when run from inside an agent it excludes the calling agent's
own session so `-a` cannot wait on itself. `-p/--project` scopes target resolution and
the `--all` snapshot to one project.

By default the command stops when a target cannot progress without a human: a pending
question, a submitted plan awaiting review, or a stopped artifact with no completion
marker exits `3`. Use `-w/--wait-blocked` only when you want the gate to keep polling
through those states. `-t/--timeout` exits `4` if unfinished targets remain after the
duration, and `-i/--interval` pins the poll interval instead of using the adaptive
default.

Exit codes are `0` when every target succeeded, `1` when any target finished
unsuccessfully, `2` for command usage or resolution errors, `3` for human-blocked
targets without `-w`, `4` for timeout, and `130`/`143` for `SIGINT`/`SIGTERM`.
Precedence is `1 > 3 > 4` when more than one condition applies.

Progress output goes to stderr. The final settle summary goes to stdout, and `-j/--json`
prints one stdout JSON envelope with no progress noise, so gate JSON and command
substitution both stay predictable.

`sase agent list -j` reports every live runner-slot waiter as `status: "QUEUED"`,
whether it is waiting on the global budget or an authored `%queue(capacity=N)`
weighted-load threshold. Its `queue_weight` reports requested capacity units, and
`runner_slot_queue_position`/`runner_slot_queue_size` rank the same waiters in the
capacity-aware display order used by sase's TUI: eligible waiters first, then parked
waiters by current blocker severity, with priority and request FIFO preserved inside
each group. A waiter parked by an [agent hold](#sase-agent-hold) also reports the
blocking hold's armer in `held_by` and that hold's expiry in `hold_expires_at`. Each
entry also exports the epic-follow state: `wait_for_epics_of` (armed follow targets) and
`epic_follows` (per-target `launching` / `following` / `blocked` stages with `epic_ids`,
`added_bead_ids`, and blocker details). `sase agent wait` rows use the same shared
phrasing (`↪ waits on <target>'s epic <id>`) as the TUI lanes.

### `sase agent hold`

An agent hold is a durable, reverse-wait admission barrier: while it is active, matching
agents stay WAITING or QUEUED instead of starting, and matching procs that have not been
dispatched yet stay pending. `sase agent hold` is the standalone CLI for the hold store
that the [`%hold` directive](macros.md#hold-directive) also describes in prompt text.
The CLI and directive are available without a feature flag. Use the CLI when you need to
inspect, release, or arm a hold outside a launch prompt.

```bash
sase agent hold create -n planner -t nightly   # block one name plus a tribe
sase agent hold create -f -s host -T 45m       # fence every later launch on this host
sase agent hold run -- just check-full         # quiesce while one command runs
sase agent hold list -j
sase agent hold show -k cli:myhost:12345
sase agent hold release                        # release this shell's or agent's own hold
```

`create` requires at least one selector: positional `SELECTOR` arguments (a name, or an
`@tribe`, expanded the same way as `%hold` names and tribes), repeatable `-n/--name` (an
agent, agent session, clan, workflow, or named proc name; role-suffixed names stay
exact), `-t/--tribe` (with or without `@`), and `-H/--hood`, plus `-f/--future` (agents
and undispatched procs submitted after the hold is armed) and `-p/--pending` (freeze the
WAITING/QUEUED agents in scope right now; it does not capture undispatched procs or
later launches). `-s/--scope` is `project` (the default, inferred from the current
checkout or agent) or `host`. `-T/--ttl` accepts bare seconds or a single-unit duration
such as `90s`, `45m`, or `2h` (compound values like `1h30m` are accepted only by
`%hold(ttl=...)`, not by `-T`); it defaults to `agent_hold_default_ttl` (`2h`) and may
not exceed `agent_hold_max_ttl` (`12h`); see
[agent hold limits](configuration.md#agent-hold-limits). Arming, releasing, and TTL
expiry post notifications; the expiry notice includes the exact boundary. sase's TUI
Admin Center lists and releases active holds.

Each armer owns one hold. Inside an agent run the armer is that agent (`agent:<name>`),
and the hold is dropped once the agent's session settles. From a plain shell the armer
is `cli:<machine>:<pid>` anchored to the parent shell, so the hold lasts until it is
released, its TTL expires, or that shell exits. `sase agent hold release` releases the
calling agent's or shell's own hold unless `-k/--key` names another armer key, and exits
`1` when no such hold is active. `sase agent hold show -k KEY` prints one hold,
including its frozen pending artifact directories and launch-time capture summary (`-j`
prints the raw record), and exits `2` when the key has no active hold. Older records
without that evidence display “capture not recorded.”

`sase agent hold run [selectors] -- COMMAND` arms a hold anchored to the `run` process,
runs `COMMAND`, releases the hold on success, failure, or interruption, and exits with
the command's status. With no selector flags it defaults to `-f -p`, the selector-free
quiesce recipe. Holds whose armer has died or whose TTL has passed are pruned whenever
the store is read.

### `sase service`

The service host supervises machine-level daemon procs independently of the TUI that
started them. Bare `sase service` is read-only and delegates to `sase service status`;
bare `sase service proc` delegates to `proc list`.

```bash
sase service status
sase service start
sase service proc list
sase service proc restart scheduler
sase service proc run -- just check
```

`start`, `stop`, and `restart` control the host; `run` intentionally owns the foreground
terminal. `logs -n N` prints the bounded host log. `status -j` emits the host and every
configured proc as JSON and exits `0` while the host is running or starting, otherwise
`1`. When a native unit is installed, lifecycle commands use that platform manager;
otherwise `start` uses the detached host path.

`sase service status` prints the host summary (plus the host config error when one is
set) and a proc table with `Restarts` and `Last exit` columns; the proc `State` column
is colored by the same severity vocabulary as the Services tab (`crash_loop` and
`backoff` fail, `exited` fails while desired running (a clean give-up only warns),
`unavailable` warns, `disabled` and operator-stopped are muted). Below the table it
repeats the blockers and warnings `sase service init` would report, such as provider
CLIs missing from the captured `PATH`, a refused or login-session-only GitHub
credential, and service procs whose executable cannot be found.

When `service.procs` stops loading (for example a YAML error in a machine overlay), the
host keeps supervising its last-known-good configuration and reports the load error as
`Host error:` until the configuration loads again; running procs are not stopped because
the new configuration is unreadable. A proc the restart policy gives up on — a clean
exit under `restart: on-failure`, or any exit or spawn failure under `restart: never` —
is parked: the host stops relaunching it and it stays `exited` with its last exit until
`sase service proc start NAME` or `restart NAME` revives it, or its configuration
changes. A proc that enters a crash loop, or a desired-running proc that is parked,
raises a `service` [notification](notifications.md) naming the reason, restart count,
and log path; a parked proc's notification also names the reviving
`sase service proc start NAME` command.

`sase service proc list` carries the same `Restarts` and `Last exit` columns and
additionally exposes effective configuration, machine enablement, desired state, runtime
state, source, launcher, and log path. `show NAME` reports uptime, the restart count,
the last exit and when, the current restart decision reason, stop provenance, the
description, and any pending start/restart request. `start NAME` and `restart NAME`
record a durable request that the host consumes, then wait for the host to confirm it: a
restart prints `service proc NAME restarted: pid OLD -> pid NEW`, a start prints
`service proc NAME started: pid N` (or `already running: pid N`), and either exits
non-zero when the host cannot confirm, the proc is disabled or unavailable, or the host
is not running. A start or restart request also clears this boot's stop marker.
`-n/--no-wait` returns as soon as the request is recorded and `-t/--timeout SECONDS`
bounds the wait (default: the proc's stop timeout plus 10 seconds, at least 15).
`stop NAME` stops the proc until the next boot; `enable NAME` and `disable NAME` persist
a machine-local override. `logs NAME` prints that proc's bounded log. A configured proc
that is invalid remains visible as unavailable rather than preventing unrelated entries
from running.

`sase service proc run -- COMMAND...` submits a transient oneshot through the durable
proc service. It does not add the command to daemon desired state and the host never
replays it after restart. It runs outside the service host's process tree, records its
exit code, and appears in the Services tab's oneshots section under a `#1`–`#9` index;
at most nine can be running at once, and finished ones never count. The TUI's `!!`
background commands use this same path. `-c/--cwd`, `-l/--label`, `-p/--project`, and
`-w/--workspace` add attribution; `-j` emits the created proc record.

Install or inspect the native user unit with `sase service init`. Without `--yes` it
prints a plan; `--check` is read-only and exits non-zero on drift, `--diff` includes the
unit and redacted captured-environment diff, and `--yes` applies. Linux uses a systemd
user service and macOS uses a LaunchAgent. A non-default `SASE_HOME` requires `--force`,
which creates a home-scoped unit identity. `sase service uninstall` has the same
plan/check/diff/apply shape; `--force` is also required when uninstalling the
non-default-home unit. See [service configuration](configuration.md#service) and
[initialization](init.md#service-host).

`sase proc` operates on durable procs: rows in `~/.sase/procs/procs.jsonl` with combined
output logs under `~/.sase/procs/logs/`. New `sase proc run` submissions always create
`command` rows under a supervisor; `--session` only controls attribution, and
`--session none` records an unattributed command visible in every session scope.
Historical `detached` rows remain readable and controllable. `sase task` is still
accepted as a deprecated alias.

The supervisor is independent of the submitting shell or TUI, so command work survives
TUI restarts and runs with no TUI open. The compact list markers are `⌘` for `command`,
`▣` for `tui`, and `◆` for historical `detached` rows; `sase proc show` spells out the
kind and ownership. Use `sase proc kill REF` to stop any active store-backed proc. JSON
output uses a `procs` array for `list` and a `proc` object for `run`, `show`, and
`kill`. Retention keeps every pending or running proc plus the newest
[`procs.history_limit`](configuration.md#procs) finished ones. See the
[sase's TUI Procs tab](ace.md#durable-procs) for the full model and the in-TUI
equivalents.

`sase proc run -N/--name NAME` and `sase proc list -N/--name NAME` address a proc by a
**named proc** instead of its id: a bare name is derived beneath the calling sase-agent
(outside a sase agent a bare name is an error), while a fully qualified name
(`<agent>--<name>`; names may not contain `/`) is resolved exactly before falling back
to an exact proc id, then a unique id prefix. Active uniqueness is scoped per project,
and a name may be reused only after the proc holding it settles. `sase proc show REF`
and `sase proc kill REF` accept the same named proc, id, or id-prefix forms (an id
prefix needs at least three characters).

Every command group with an exact `list` child defaults to that list view when invoked
bare — `sase agent`, `sase agent-cli`, `sase artifact`, `sase bead`, `sase chat`,
`sase completion`, `sase disk`, `sase file`, `sase file-history`, `sase file-hook`,
`sase final`, `sase flag`, `sase gate`, `sase goal`, `sase instructions`,
`sase machine`, `sase memory`, `sase migrate`, `sase monitor`, `sase notify`,
`sase plan`, `sase plugin`, `sase proc`, `sase project`, `sase prompt`, `sase repo`,
`sase skill`, `sase snippet`, `sase stitch`, `sase sudo`, `sase telemetry`, `sase tool`,
`sase usage`, `sase var`, `sase workspace`, and `sase macro`. Nested groups such as
`sase agent hold`, `sase agent prompts`, `sase agent tribe`, `sase artifact link`,
`sase artifact link relation`, `sase artifact trash`, `sase axe job`,
`sase axe routine`, `sase bead dep`, `sase bead ref`, `sase bead task-type`,
`sase memory web`, `sase patch ref`, `sase plan links`, and `sase project alias` follow
the same rule. A bare invocation prints a short notice naming the delegation, for
example `No subcommand provided for 'sase repo'; delegating to 'sase repo list'.` Groups
without a `list` child, such as `sase patch`, `sase axe`, or `sase bead pages`, do not
delegate.

This is a property of the parser, not a hand-maintained list: any group that gains an
exact `list` child picks the behavior up automatically.

The bare form is only the default view. When you need flags that belong to the list
command, keep the `list` subcommand explicit, for example `sase notify list -j`,
`sase agent hold list -j`, or `sase workspace list --json`.

## Work Tracking And Planning

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase patch](reference/cli/patch.md), [sase bead](reference/cli/bead.md),
  [sase plan](reference/cli/plan.md), [sase goal](reference/cli/goal.md),
  [sase project](reference/cli/project.md)
- [sase init](reference/cli/init.md), [sase machine](reference/cli/machine.md),
  [sase memory](reference/cli/memory.md),
  [sase instructions](reference/cli/instructions.md), [sase repo](reference/cli/repo.md)

Workflows: [Patches](change_spec.md), [Beads](beads.md), [SDD](sdd.md),
[Goals](goals.md), [Project lifecycle](project_spec.md), [Initialization](init.md),
[Remote dispatch](remote_dispatch.md), [Memory](memory.md).

Patches are PR-sized review records. SDD stores durable prompt and planning artifacts.
Beads add git-portable dependency tracking and executable epics on top of those
artifacts.

Bead commands that take existing bead IDs — `show`, `update`, `open`, `close`, `rm`,
`note`, `+1`, `snooze`, `history`, `dep`, `ref`, `pages`, `epic-symbols`, and `work` —
resolve a full ID against the current project's store first and then route it to the
enabled project that owns it, so `sase bead close bob-cli-1e --note done` works from
another project. Shorthand suffixes stay local, mutating commands reject batches that
span more than one store before writing, and `sase bead create` places a child in the
store that owns a full parent ID. Commands without a bead selector (`list`, `search`,
`ready`, `blocked`, and `stats`) keep the current-project scope. See
[Bead ID Arguments](beads.md#bead-id-arguments).

`sase project` defaults to `sase project list`, and `sase project list` defaults to
enabled true projects. `sase project current` prints the current project derived from
the VCS macro MRU head — the project name in that project's accent color, its canonical
directory key, whether it came from a project ref or a Patch, and the MRU ref that
produced it. Launch an agent on a project (or on a Patch owned by that project), or run
`sase project set-current`, to change it — sase's TUI binds the same operation in the
Projects tab. When nothing resolves, the command explains that and exits 0. Use
`sase project list --state all --json` to inspect disabled projects and internal
`sibling` backing records, `sase project disable <project>` to hide a dormant project
from default launch views, and `sase project enable <project>` to make it launchable
again. Disabling refuses projects with live `RUNNING` claims or active artifact markers
unless `--force` is passed. Project arguments also accept the
[project tag](macros.md#project-tags) spelling, so `sase project show +sase` works like
`sase project show sase`. `sase project list` has a `TAG` column and `sase project show`
a `Tag:` line with each project's `+<name>` spelling (`-` or omitted when the name does
not fit tag syntax), colored by project accent on a color terminal; their `--json`
output adds `tag` (`null` when the name does not fit tag syntax), `workflow_type`, and
`accent` (`null` for disabled projects). Legacy active/inactive values and the
deprecated lifecycle command aliases remain read-compatible. sase's TUI **Projects** tab
(in the SASE Admin Center, opened with `#`) provides the interactive counterpart,
including marking multiple projects, editing a ProjectSpec in `$EDITOR`, and deleting
obsolete SASE project directories after confirmation. There is no CLI delete subcommand;
full project-directory deletion is only available from sase's TUI Projects tab and
removes state under `~/.sase/projects/`, not workspace checkouts.

`sase project suggest [PROVIDER] [-a|--all] [-j|--json] [-o|--owner OWNER]... [-r|--refresh]`
ranks the repositories worth adding as projects, grouped as `RESUME`, `ON THIS MACHINE`,
`SUGGESTED`, `LINKED TO YOUR PROJECTS`, and `DISABLED PROJECTS`. Discovery is
cache-first per owner: it creates no repositories or project registrations, so agents
may call it freely. It may refresh local discovery caches, and specifying a provider
records that provider as the wizard preference. `-o` restricts discovery to the named
owners, `-r` bypasses the cached repository lists, and `-a` includes the hidden rows
(sidecars, forks, archived repositories, enabled projects, numbered clone copies, and
third-party local checkouts) that are otherwise only counted in the footer.

`sase project add REF [-a|--alias ALIAS]... [-c|--check] [-j|--json] [-m|--make-current] [-n|--name NAME] [-S|--no-setup | -s|--setup] [-Q|--request-path PATH] [-R|--result-path PATH] [-y|--yes]`
registers an existing repository. `--check` is read-only and emits one plan document
with `--json`; JSON apply streams plan, step, and result events as NDJSON. New projects
are enabled by default. Setup may write `sase/sase.yml`, commit the marker, and push the
default branch; agents can preview and register with automatic setup omitted, while
explicit `--setup` is human-only. Repeating the same command resumes an interrupted
operation. After successful setup, a TTY can hand off to `sase init -p KEY`; sidecar
creation there still requires its own confirmation.

`sase project create REF [-a|--alias ALIAS]... [-c|--check] [-d|--description TEXT] [-j|--json] [-m|--make-current] [-n|--name NAME] [-O|--option KEY=VALUE]... [-S|--no-setup | -s|--setup] [-Q|--request-path PATH] [-R|--result-path PATH] [-v|--visibility VISIBILITY] [-y|--yes]`
creates a repository (`gh:OWNER/NAME`, `OWNER/NAME`, or `git:NAME`) and registers it.
The apply argv uses a create-parseable ref (`git:NAME` for bare git). `--visibility` is
GitHub sugar and is only defaulted or emitted when the provider's creation form has a
visibility field; bare-git has none. Provider options are validated strictly before any
create subprocess. `--check` lists every provider option with its default, value, and
availability, and is available to agents. Apply refuses inside agents and monitors
(exit 2) unless it runs as an approved `/sase_gate` option or
`SASE_PROJECT_CREATE_BYPASS` holds a reason. Repeating the same command resumes an
interrupted create.

`-Q`/`--request-path` and `-R`/`--result-path` on `add` and `create` are integration
options for a durable proc: `-Q` reads an existing operation-request JSON file and
checks that its target and options match the command; `-R` writes the outcome of an
apply attempt as typed JSON, including blocked or failed attempts. `--check` writes no
result file. These companion files are unrelated to project sidecar repositories. When
the flags are omitted, SASE uses `$SASE_PROC_REQUEST_PATH` and `$SASE_PROC_RESULT_PATH`
if set; otherwise no request file is read or result file written. Ordinary interactive
commands do not need either flag.

`sase project alias list [PROJECT] [-j|--json]`, `add PROJECT ALIAS`,
`remove PROJECT ALIAS`, and `clear PROJECT` manage ProjectSpec aliases. sase's TUI
Projects sub-tab (in the SASE Admin Center, opened with `#`) also displays aliases,
includes them in filtering, and opens an alias editor with `A`. Alias refs are accepted
in launch-bound VCS workspace tags, but prompt history, agent metadata, and artifacts
use the canonical directory-key project name. ProjectSpecs may also carry `PROJECT_NAME`
as the primary user-facing name. For example, the GitHub provider can create
`PROJECT_NAME: foo` and then `PROJECT_NAME: foo_1` for distinct `owner/foo` repositories
while keeping stable canonical project records. Existing auto-aliased GitHub projects
remain valid and keep resolving through `PROJECT_ALIASES`.

Enabled-only true-project discovery is also the default for launch pickers, Patch
searches, project-local macro catalogs, broad mobile helper catalogs, and all-known bead
helper reads. Internal sibling backing records are hidden from those surfaces and
support configured linked repositories. Agents prepare one through `/sase_repo`; the
underlying audited open infers the host project and workspace from cwd. Agent-history
views that need older artifacts opt into all project states explicitly. An explicitly
typed known-project VCS ref is a launch-time exception: it re-enables a disabled project
before claiming a workspace. A checkout cwd or mobile `project` value is only
prompt-resolution context, not a workspace ref; without an explicit ref, a bare prompt
defaults to `#git:home`. Direct low-level claims against a disabled ProjectSpec remain
blocked until the project is enabled.

`sase plan` defaults to `sase plan list`. The dashboard has Proposed, Approved, and
Rejected sections; use repeatable `-s/--status` options to select sections, `-n/--limit`
to set each history section's size (`0` is unlimited), and `-t/--tier` to filter by
plan-file tier. Proposed rows are never limited and are the actionable rows; each leads
with the plan `name` in bold cyan (shortest unique form, with the dim `id_prefix` below
it), plus agent, project, provider/model, plan path, and response directory. A hint line
under the section shows the ready-to-paste approve/reject commands for the first name.
Pass the plan name to `sase plan approve <name>` or `sase plan reject <name>` (a
`<shard>/<name>` path, filesystem path, `plan:` ref, planner agent, or notification
ID/prefix works too; names TAB-complete). Proposed `--json` rows carry the same `name`
field. If the selector is omitted, exactly one pending proposal must exist. When
`--kind` is omitted, approval defaults to `tale`; epic-authored plans require an
explicit `--kind epic` or `--kind tale`. The Rejected section is inferred from archived
proposal files that are not represented by the proposed or approved state; it is a
history aid, not the selector source for new actions. The approval kind is the workflow
choice: `approve` runs the coder without asking the runner to commit an SDD plan, `tale`
commits the plan as an SDD tale and then runs the coder, `epic` commits the matching SDD
tier and launches the bead follow-up, and `commit` records the approved plan in SDD
without launching a coder. Use `-m/--model` to pick the follow-up agent's model. Use
`-p/--prompt` to add extra coder instructions for the `approve` and `tale` paths. A plan
with no live gate can be named by path, `plan:` reference, archive name, or unavailable
gate ID: it is approved directly and starts a `#coder` in the planner's agent session
when it can safely attach, otherwise as a standalone agent. The coder launch runs a
ladder: it relocates to a pool workspace when the planner's workspace is taken, falls
back to standalone when the agent session cannot be joined, and retries once on
transient claim errors. Only unlaunchable-machine errors (missing owner identity,
unknown project tag, hard-disabled provider, or an unspawnable process) fail the launch.
On failure the card prints `sase plan approve <local plan path>` to re-run every
fallback and record the receipt. `-n/--dry-run` renders that decision without changing
state, and `-P/--project` supplies project context for the direct route. Re-approving an
already-approved plan relaunches its coder when that coder failed, was killed, or never
launched, and refuses when the coder is still running or has finished. Tale and epic
approvals validate against their target schema before writing a response; a failure
prints the diagnostics and expected schema and leaves the proposal pending for retry.
Plans can also declare typed choices and toggles as Plan Decisions. Ordinary approval
accepts their effective defaults; pass `-D/--decide ID=VALUE` to approve with different
values, or use `sase gate answer` with `--set decision_<id>=<value>` to override them on
a pending gate. See [Plan Decisions](sdd.md#plan-decisions) for the grammar,
memory-consent rules, and current interface limits.

`sase plan reject` writes the rejection response first, then uses the same durable
cleanup path as the TUI no-feedback rejection action when the matching planner row is
still discoverable. If cleanup cannot find or kill the row, the CLI reports that
separately after the plan has already been rejected.

`sase plan search [QUERY]` searches plans in the resolved SDD store (the `repo` source)
and the machine-local `~/.sase/plans/` archive. Omit the query to browse with metadata
filters. Compact and Markdown output group SDD-store matches above local matches; JSON
and full output keep ranked result order with SDD-store matches prioritized over
otherwise-similar local matches. Useful filters include `--kind`, `--status`,
`--source`, `--since`, `--until`, `--sort`, and `--format json|markdown` for
agent-friendly output.

`sase plan show [TARGET]` resolves any way a user can name a plan to exactly one plan
and renders it. In `-t auto` (the default), TARGET is tried against five rungs in order
and the first definitive match wins: `path` (an existing file, absolute or
cwd-relative), `ref` (a `plan:` reference, a legacy marker path, or a month-drifted
reference, Rust resolved), `proposal` (any pending-plan selector `approve`/`reject`
accept: name, `<shard>/<name>`, planner agent, or notification id/prefix), `name` (a
corpus slug or `<shard>/<slug>` lookup, with or without `.md`), and `bead` (a bead id
whose `design` field points at a plan). Pass `-t/--target` to force one rung with no
fallthrough. Omit TARGET to show the sole visible pending plan proposal, exactly as
`sase plan approve`/`reject` treat an omitted selector. Every ambiguity prints its
candidates as re-runnable `plan:` references and every miss prints close-match
suggestions; neither guesses. `-f/--format` selects `full` (the default
section-structured detail view, matching the PLAN lane in sase's TUI), `compact` (the
same row `sase plan search` prints), `json` (a schema-versioned envelope), or `raw` (the
plan file's exact text, for piping). A plan that fails validation still renders in full
with its diagnostics shown and exits `0`; only a missed, ambiguous, or unreadable target
exits `1`. `-w/--wrap` controls goal/phase/diagnostics prose wrapping, and `-c/--color`
matches `sase bead show`.

`sase plan validate PLAN_FILE` reads the required `tier: tale|epic` property and
validates exactly one path without requiring a project or agent context. With Plan
Decisions, agent-context validation also checks memory selectors and human-request and
corrected-claim quotes; outside an agent, quote verification is deferred to proposal. It
reports every schema problem in one run and prints the expected tier schema plus a
minimal valid example on failure. Use `-e/--explain` for tier-specific authoring
guidance, `-j/--json` for the stable machine-readable envelope, or `-q/--quiet` to
suppress the successful human summary. A plan that has decisions also prints the
Decision Sheet after the result, and, when the live `%auto` spelling covers the plan's
tier, `auto-approved: every decision takes its default`. When the spelling does not
cover the tier, sase prints `%auto:<mode>` does not cover `<tier>` plans; this plan
waits for review instead. In `--json` mode stdout stays one JSON document: the sheet,
the `%auto` note, and the outside-agent quote-verification note live inside the
`decisions` envelope while the same human text goes to stderr. See the
[validation output](sdd.md#plan-frontmatter-schema-and-validation). The removed
`-t/--tier` option is now invalid command usage. A valid plan exits 0, a validation
failure exits 1, and invalid command usage exits 2.

### `sase goal`

Goals are durable records a person creates, lists, shows, edits, drops, reopens, and
merges. Bare `sase goal` defaults to `sase goal list`, which shows unsettled goals with
an honest freshness header (`synced Ns ago`, `local only`, or `never synced`) and footer
chips (`↑ unpublished`, `refreshing…`, `⚠ N unreadable`). `-s/--status` filters the
list; `done`, `dropped`, `settled`, and `all` scan history newest-first with `-n`
defaulting to 20. `-j/--json` emits the wire structs the gateway consumes. `new`,
`edit`, `drop`, `reopen`, `merge`, and `doctor --repair` are human verbs and refuse
inside agent runs; `list`, `show`, and `doctor` work everywhere. See [Goals](goals.md)
for the full tour.

## Automation

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase scheduler](reference/cli/scheduler.md), [sase axe](reference/cli/axe.md)

Workflows: [Scheduler](axe.md).

The scheduler runs scheduled hooks, mentors, comment polling, workflow checks, `%wait`
dependency resolution, cleanup, and error digests. sase's TUI starts the service host
unless launched with `sase tui --no-service` (`--no-axe`).
`sase axe start|stop|restart|status` is an alias of the matching `sase scheduler`
command. The older `sase axe chop ...` and `sase axe lumberjack ...` spellings remain
hidden compatibility aliases for `sase axe job ...` and `sase axe routine ...`; see
[Compatibility aliases](axe.md#compatibility-aliases).

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase monitor](reference/cli/monitor.md), [sase pipe](reference/cli/pipe.md)

Workflows: [Monitors](monitors.md).

A long command (`just check-full`, a CI wait, a deploy) should run under a monitor
rather than blocking an agent turn — see the `/sase_monitor` skill. Handing this agent's
own turn to a successor is a different, in-process hand-off — see the `/sase_handoff`
skill.

## Prompt And Workflow Authoring

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase macro](reference/cli/macro.md), [sase lsp](reference/cli/lsp.md),
  [sase editor](reference/cli/editor.md), [sase file](reference/cli/file.md),
  [sase file-history](reference/cli/file-history.md),
  [sase skill](reference/cli/skill.md), [sase snippet](reference/cli/snippet.md)

Workflows: [Macros](macros.md), [Workflows](workflow_spec.md),
[Editor integration](editor.md).

Use `#name(...)` for inline macro expansion and `#!workflow(...)` for standalone
workflow references. Workspace references such as `+<project>`
([project tag](macros.md#project-tags)), `#git:<project>`, and plugin-provided
references are resolved before the prompt or workflow runs.

## Review And Delivery

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase final](reference/cli/final.md), [sase stitch](reference/cli/stitch.md),
  [sase revert](reference/cli/revert.md), [sase restore](reference/cli/restore.md),
  [sase comments](reference/cli/comments.md)

Workflows: [Commit workflows](commit_workflows.md), [VCS](vcs.md),
[Mentors](mentors.md).

Delivery commands delegate to the VCS and workspace provider layers, so the same command
surface can support plain git, GitHub pull requests, and other provider plugins.

## Operations And Diagnostics

Flag and option details live in the generated
[CLI command groups](reference/cli/index.md):

- [sase doctor](reference/cli/doctor.md), [sase config](reference/cli/config.md),
  [sase usage](reference/cli/usage.md), [sase flag](reference/cli/flag.md),
  [sase file-hook](reference/cli/file-hook.md), [sase core](reference/cli/core.md)
- [sase migrate](reference/cli/migrate.md), [sase validate](reference/cli/validate.md),
  [sase telemetry](reference/cli/telemetry.md), [sase version](reference/cli/version.md)
- [sase plugin](reference/cli/plugin.md), [sase update](reference/cli/update.md),
  [sase completion](reference/cli/completion.md), [sase logs](reference/cli/logs.md),
  [sase revive-log](reference/cli/revive-log.md)
- [sase artifact](reference/cli/artifact.md),
  [sase agent-cli](reference/cli/agent-cli.md), [sase var](reference/cli/var.md),
  [sase path](reference/cli/path.md), [sase repo](reference/cli/repo.md),
  [sase tool](reference/cli/tool.md), [sase disk](reference/cli/disk.md),
  [sase workspace](reference/cli/workspace.md), [sase mobile](reference/cli/mobile.md)

Workflows: [Configuration](configuration.md), [Plugins](plugins.md),
[Shell completion](completion.md), [Telemetry](telemetry.md), [Workspace](workspace.md),
[Mobile gateway](mobile_gateway.md).

The `sase artifact show`, `read`, `path`, `open`, and `link` commands take logical
references without a leading `@`, for example
`sase artifact show file:default:<digest>`. Add the sigil when embedding the same
reference in a launch prompt: `sase run "review @file:default:<digest>"`. This
bare-CLI/`@`-in-prompts rule also applies to document roles, chats, beads, agents,
commits, and bugs. `path` accepts only references with a filesystem identity; `open` can
also open a bug in a browser but rejects commits.

`stats`, `prune`, `reclaim`, and `trash` are the store's lifecycle commands, and they
are deliberately staged: `stats` only reports, `prune` and `reclaim` print a plan and
change nothing unless `--apply` is passed, and every removal either of them makes moves
the stored bytes **and** the complete index row into a restorable trash under
`~/.sase/artifacts/trash/`. `sase artifact trash restore` puts an entry back; only
`sase artifact trash purge` deletes permanently, and without `-a/--all` it purges only
entries older than `artifacts.retention.trash_grace_days`. Trashed bytes still occupy
disk until that purge runs. Explicit artifacts, artifacts a ProjectSpec, plan, bead, or
research document references, artifacts recorded in the consumption ledger, and the
newest capture of every label are never selected; if a required protection source cannot
be read, `--apply` refuses rather than under-protecting. See
[Store Lifecycle](agent_images.md#store-lifecycle).

`sase artifact list` inventories only the persistent artifact-file index; it is not a
catalog of every reference kind and it does not browse the agents-sidecar prompt
archive. Use `sase agent prompts list/show/validate` for archived prompts and their
published `ARTIFACTS` links. Use sase's TUI grouped `@` completion to browse prompt
references, or its contextual **Copy as…** palette to copy a reference or pre-fill a new
agent prompt from the selected entry. See
[Getting Started](getting_started.md#step-6-hand-off-existing-work-with-artifact-references)
for the handoff workflow and
[prompt preprocessing](llms.md#prompt-preprocessing-pipeline) for launch-time
resolution.

Operational commands are intentionally narrow. Helper bridges expose fixed JSON
operations for editor and mobile clients; they are not general shell or filesystem APIs.

`sase --full-help` also lists durable-operation entrypoints that sase's TUI submits as
durable procs rather than commands meant for everyday typing: Patch lifecycle actions
(`sase patch accept`, `archive`, `mail`, `rebase`, `restore`, `revert`, `rewind`,
`reword`, `status`, `submit`, `sync`, and `tag`), `sase agent revert`,
`sase agent persist-cleanup`, `sase agent persist-directive`, `sase bead apply-status`,
and `sase notify apply-state` / `apply-state-many`. They take `-Q/--request-path` and
`-R/--result-path` for the private request and typed result sidecars, defaulting to
`$SASE_PROC_REQUEST_PATH` and `$SASE_PROC_RESULT_PATH`. Several everyday commands, such
as `sase run`, `sase agent drain`, `sase gate act`, `sase launch approve`, and
`sase plugin install`, accept the same two options so the TUI can run them as procs.

### Doctor Support Reports

`sase doctor` is the first command to run when SASE behaves unexpectedly. It is
read-only by default (apart from the agent-hold reconciliation described below): it does
not launch agents, call LLM APIs, repair state, run tests, or scan full artifact
history. The human output is grouped by subsystem and puts next-step commands beside
warnings and errors.

Common forms:

```bash
sase doctor                 # compact human report
sase doctor -v              # include every check plus bounded details
sase doctor -j              # stable JSON report for scripts or support bundles
sase doctor -D              # add slower read-only deep checks
sase doctor -C runtime      # run one group
sase doctor -C llm.default  # run one check
sase doctor -C project.junk_directories -C workspace.missing_checkouts
sase doctor -F              # preview and confirm ProjectSpec duplicate-block repair
sase doctor -R              # preview and confirm restore of stranded primary sidecar link-index deletions
```

Exit codes are designed for support-first use. `OK`, `WARN`, and all-skipped reports
exit `0`; `ERROR` exits `1`. Use `sase doctor -s` / `--strict` when automation should
treat warnings as failures.

The JSON report uses `schema_version: 1` and stable top-level fields such as `status`,
`counts`, `selected_checks`, and `checks`. Individual check `data` payloads stay bounded
and may gain additional keys over time, so scripts should key off check ids and statuses
rather than assuming every nested field is permanent.

The `completion` group is advisory and never fails a report: `completion.install` reads
the [shell-completion](completion.md) install stamps, and the deep-only
`completion.registration` spawns a real shell to confirm the script is actually
registered (`sase doctor -D -C completion.registration`). Selecting a deep check without
`-D` is rejected rather than silently skipped.

`plugins.commands` loads mounted command adapters and reports command and claim
problems. A load failure is `ERROR` on this check. A name collision is `ERROR` and names
every owner; the suggested next step is an uninstall command for the first owner
alphabetically; doctor does not run it. A shadowed or invalid name is `WARN`. The
deep-only `plugins.commands-parsers` check
(`sase doctor -D -C plugins.commands-parsers`) also builds each mounted command's
parser, and a parser failure is `ERROR` too. A load or parser failure's suggested next
step currently uses `sase plugin update <command-name>`. The command name may differ
from the plugin name; use the owning distribution in the diagnostic to identify the
plugin before updating it. See
[Where a command shows up](plugins.md#where-a-command-shows-up).

`project.junk_directories` reports directories under `~/.sase/projects/` that have no
canonical ProjectSpec and gives a manual-review cleanup hint.
`project.duplicate_patch_blocks` reports duplicate raw Patch blocks in active and
archive ProjectSpec files. `sase doctor -F` / `--fix-duplicate-blocks` previews that
repair and, after confirmation or `-y` / `--yes`, keeps the newest block per Patch name
without changing the default read-only doctor behavior.
`project.primary_sidecar_link_dirt` flags uncommitted `links/` dirt in sidecar clones
nested under a project's primary checkout, which blocks pull-based sidecar auto-sync.
`sase doctor -R` / `--fix-primary-sidecar-links` restores stranded canonical link-index
deletions (`git restore`) as a user-origin action; it does not commit them, because
durable deletions must land via the machine write lane and reach the primary through
auto-sync. `workspace.missing_checkouts` scans enabled and disabled projects through the
shared inventory, lists registered checkout paths missing from disk, and suggests a
per-project `sase workspace repair -n` preview. `workspace.occupancy_conflicts` reads
every project's RUNNING field and each checkout's occupant record, then reports
duplicate workspace-number claims, a live claim whose occupant names a different live
pid, and occupant records with no matching claim. Conflicts include the last
workspace-claim ledger mutation and caller tag when one exists; the check never
auto-repairs. `config.macro_directives` locates macro and workflow definition files that
still use retired directive syntax, such as a `%wait(priority=...)` that has moved to
`%queue`. `agent_holds.stale` warns about [agent holds](#sase-agent-hold) whose armer
has died or whose TTL has passed; like `sase agent hold list`, it reconciles the hold
store as it reads it, so the stale records it reports are also pruned. Apart from that
reconciliation, default doctor checks do not mutate state.

When asking for help, attach `sase doctor -v` for a readable report or `sase doctor -j`
for a machine-readable report.
