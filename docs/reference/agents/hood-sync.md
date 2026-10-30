---
title: Agent hood synchronization
description: Look up shared hood privacy, layouts, publication, browsing, and recovery.
---

# Agent hood synchronization

This page describes the shared hood format and the user-facing synchronization behavior.

SASE publishes deterministic project-scoped agent-hood snapshots and canonical prompt
archives through each managed project's hidden `agents` sidecar. The machine-level clone
lives under `~/.sase/projects/<project-key>/repos/agents`; it is never exposed to
launched agents or copied into numbered workspaces.

## Privacy and configuration

One publication includes every locally owned active, waiting, terminal, failed, and
dismissed run in the committing agent's complete top-level hood. Active prompts can
therefore appear before a transcript exists; later syncs can refresh the stable run with
terminal state, commits, or a readable chat. Portable metadata and session/clan
relationships are included as well. Creating or pushing the sidecar publishes that data
to everyone who can read the configured remote.

Before running `sase repo init`, set the intrinsic `agents` sidecar's
`visibility: private` when that scope must remain restricted. Set `disabled: true` to
opt out entirely. Synchronization never creates a remote and cannot bypass the explicit
consent requested by repository initialization.

Both the initial privacy-forward scaffold and the manifest-derived root browsing index
display the same static infographic. `sase repo init` owns
`assets/agents-directory-map.png`: rerunning it creates or repairs the image without
replacing a populated sidecar's derived `README.md`. Agent synchronization owns only the
dynamic publication paths.

Every publisher needs a complete selected `id.username` / `id.machine_name` owner
identity. Local artifacts keep bare semantic names such as `foo.bar--code`; v2 transport
uses the canonical global name `<username>.<machine_name>.foo.bar--code`. The exact
owner manifest is the only shared authority file that publisher mutates. Run
`sase config init` to create or migrate the identity; see
[owner identity and machine overlays](../config/files-and-merging.md#owner-identity).

## Strict v2 layout

```text
README.md
schema.json
assets/
  agents-directory-map.png
users/<username>/README.md
users/<username>/machines/<machine>/README.md
users/<username>/machines/<machine>/manifest.json
users/<username>/machines/<machine>/hoods/<hood>/README.md
users/<username>/machines/<machine>/hoods/<hood>/snapshot.json
agents/<global-name>/
  README.md
  meta.json
  state.json
  prompt.md
  commits.json
  chat.md                 # only when readable
sessions/<global-session>.md
families/<global-session>.md   # permanent redirect stub for historical footer links
prompts/<YYYYMM>/<name>.md
prompts/<YYYYMM>/README.md
files/objects/sha256/<hex-prefix>/<sha256>
```

An artifact reference such as `@agent:foo` or `@agent:<username>.<machine>.foo`
addresses `agents/<global-name>/README.md` in the selected project's agents sidecar.
Local semantic names are accepted in the current owner's context and canonicalized to
the durable global name; published prompts, plans, and bead descriptions should prefer
the global spelling. Agent references do not accept `#L`, `#page=`, or `#t=` fragments.
If the page has not been published yet, run `sase agent sync` for the project before
sharing the `@agent:` reference.

Owner manifests map each hood to its snapshot digest plus run and session counts. The
snapshot itself lists every referenced file with its size and SHA-256 digest, so the
manifest does not need to repeat that file set. Every manifest write (a fresh
publication or either repair command below) omits the per-hood `files` list, which keeps
an owner manifest small even for owners with thousands of hoods. Readers always accept a
missing `files` list. When a list is present, two exact sorted unique sets are accepted.
The current set names the hood snapshot and hood README, each run's agent README and
recorded file paths, and, for every session or family container, both
`sessions/<global>.md` and `families/<global>.md`. Clan containers add no pages. The
legacy set is that same list with every `sessions/` path removed, so it still includes
the `families/` redirect stubs. It is a second accepted shape only when the current set
contains `sessions/` paths. A hood with no session or family container has one set, and
that set is current. Any other list is a mismatch. A matching list does not skip the
other checks: a changed snapshot digest or a changed referenced file still fails
publication. Owner manifests have their own read caps (16 MiB and 16,384 hoods), and a
write that would exceed them fails before anything lands. SASE versions that predate the
optional list treat a slim manifest as malformed and skip that owner when they rebuild
shared indexes, so upgrade every machine that publishes to a shared sidecar.

Snapshot and per-run JSON is strictly versioned, canonically encoded, size/count
bounded, and content-addressed with SHA-256. Names and paths are validated as single
components, and every relationship/container batch passes through the Rust identity
facade before publication. A publication re-reads the referenced files only for the
hoods it is writing; every other hood still has its snapshot digest and identity
checked, so a drifted file in one hood does not block publication of another.

The allowlist excludes PIDs, workspace numbers, credentials, absolute paths, checkout
paths, and other host-local execution state. A publication is fully built and validated
before rollback-safe atomic writes begin, so malformed input cannot leave a
half-rendered hood.

## Prompt and artifact archive

The agents sidecar is also the canonical home for prompts published by agent-backed
commits and approved planner runs. After the primary commit succeeds,
`sase stitch create` publishes the committing run's prompt to
`prompts/<YYYYMM>/<name>.md` inline, before returning. Approving a planner's tale or
epic publishes a separate, plan-named entry before SASE continues with the plan write or
epic handoff. Plan-backed entries use the plan slug as the filename; entries without a
plan use the publishing agent's global sase-agent name. Each prompt document has the
same header-block grammar as plans:

- `PLAN` links back to the plans sidecar when the run has a plan.
- `AGENTS` links to the published agent page for the run.
- `ARTIFACTS` links to the prompt references SASE could make durable.

The default, primary body depends on how the entry was published:

- A normal commit publication uses `raw_macros.md`: SASE has resolved project and
  configured macro aliases, but has not expanded the macros. Reusable `#...` references
  therefore remain visible.
- An approved planner publication uses the plan snapshot: macros and workflow
  `prompt_part` content are dry-expanded and prompt directives are removed, without
  running workflow pre- or post-steps.

In both cases, staged `@...` references in the primary body become durable links when
possible.

Launch-time staging records prompt references in the workspace-local
`.sase/artifacts/prompt-artifacts.jsonl` manifest. When a prompt archive is published,
external file bytes are copied from `.sase/artifacts/pool/` into the agents sidecar
under `files/objects/sha256/<hex-prefix>/<sha256>`. The path is derived from the file's
SHA-256 digest, so identical bytes publish once and differing bytes do not overwrite
each other. Clean tracked files inside known repositories are not duplicated; their
prompt links point to hosted source blobs at the recorded revision. Non-file references
such as `@agent:`, `@patch:`, and `@stitch:` remain links without copied bytes.

Objects are committed in the same commit as the prompt that links them. `files/objects`
is append-only: a pool copy lives in an ephemeral workspace, so a discarded object
cannot be regenerated, and the cleanup that resets `prompts/` before each publication
never resets, restores, or deletes under it. Before every `git pull --rebase`,
publication also sweeps untracked paths under `files/objects` while holding the sidecar
lock. Each one whose path is canonical (`files/objects/sha256/<xx>/<sha256>`, a regular
file, prefix matching, and bytes hashing to its name) is committed as
`chore(agents): publish pending prompt-archive objects`, which also publishes objects
left behind by an interrupted publication or an older SASE. Committing first lets an
identical object that another machine already published rebase cleanly. Any other file
is moved, never deleted, to `<git-dir>/sase-quarantine/objects/<utc-timestamp>/` and
logged, so it can never wedge the worktree.

Prompt-archive publication is not a separate durable queue. The outbox request enqueued
for a commit's hood also owns its prompt. The inline commit path publishes the archive
directly; when the background path is selected, the publisher regenerates it from the
local artifact pool inside the same bounded transaction that publishes the hood. A
request is acknowledged only once both halves reached the sidecar, so a prompt that
could not be rebuilt keeps its request queued and retryable rather than retiring it.

Document back-references are separate. After verified prompt-archive publication that
contains a provider-document reference, SASE records the citation. The inline commit
path tries to publish it before returning; the background publisher drains it after the
archive is published. That attempt cannot delay or roll back the prompt publication that
already completed.

In an unfenced project the citation is a row in
`~/.sase/projects/<project-key>/referenced-by-outbox.json`. The drain pulls the cited
artifact sidecar, updates its managed `Referenced By` table, and acknowledges the
request after a successful local refresh. A later detached push failure is recorded in
the managed SDD sync log rather than restored to this outbox. Refresh failures charge
attempts and quarantine at the publication threshold. Queued requests use the same
retry, quarantine, and retired-entry operator controls as hood publication.

In a fenced (link-v2) project SASE never takes that sidecar lock or pulls for Referenced
By, and never enqueues a new outbox row. Planned `cites` rows are appended as
artifact-link outbox events and published by the existing link-outbox drain. On the
commit path those events use the committing run's identity so the same pass publishes
them; the approved-planner archive uses a trusted machine lane. Active legacy outbox
rows are replayed once as equivalent `migrated` cites events and then acknowledged. See
[Artifact Reference Publication](../artifact-references.md#publication) for the complete
ordering and recovery boundary.

Use `sase agent prompts list` to browse the archive. `sase agent prompts show <prompt>`
prints the archived Markdown document. `sase agent prompts validate` verifies headers,
legacy artifact links, and content-addressed `files/objects/` links. It reports missing,
untracked, and digest-mismatched objects as errors, and tracked objects no prompt links
as warnings, alongside local manifests and plan cross-links.
`sase agent prompts migrate` reports historical plans-sidecar prompts by default and
moves them to this archive only with `--write`.

Existing top-level v1 `manifest.json` and `agents/<machine-qualified-name>` bundles are
left untouched. Sync reads those records for compatibility and does not create, refresh,
import, or retire v1 transport data. Historical local imports can be swept entirely
(every transport, every machine) with `sase agent names purge-local-state`.

## Browsing page anatomy

Root, user, machine, and hood pages stay focused on indexes. Agent and session pages
carry the detailed artifact view for one run or lane, and their optional sections keep a
deterministic order so stable inputs produce byte-identical Markdown.

An agent page uses this anatomy:

- Breadcrumb: root, user, machine, hood, optional session, and the current agent.
- Summary: bead and epic links when the run is associated with a bead, above model,
  provider, timing, commit count, and variable count when variables were published.
  Non-zero counts link to their page sections.
- Files: links to the published prompt and chat when each file exists.
- Commits: the run's commit table, when any commits were attributed to the run.
- Variables: sanitized output variables, when the run published any.
- Neighbors: related sase agents in the same owner/machine hood, when any exist.

A session page keeps the `Lineage` diagram and accessible member table first, then uses
the same optional artifact order: `Commits`, `Variables`, and `Neighbors`. Session
commit and variable tables include the member role so each row can be traced back to a
member. Session neighbor rows describe the session itself and never list its own
members, which are already present in the member table.

The session page is the durable home of a session's commits. Because a commit footer
names the sase agent rather than the member, session commit history is owned by the
session container itself and is carried in the published snapshot alongside the
per-member rows. The `Commits` table unions both sources: rows recovered from a member's
own artifact keep that member's role, and sase-agent-level rows — including commits
whose member artifact has since been cleaned up — render with a `—` role. Rows are
deduplicated by SHA with the member-attributed row winning, then sorted and capped like
every other commit table. Clan containers never accumulate commits this way; only
sessions do.

When any member is associated with a bead, the session header line also names the
distinct bead ids across the session's members after `Members:` — one as `Bead: <link>`,
several as `Beads: <link>, <link>` capped at five with a trailing `… +N more`, and none
leaves the header line as it is today.

Commit cells link to hosted commit pages only when the project primary repository has a
recognized GitHub remote. If the primary remote is missing, not GitHub, or cannot be
read, pages still render the same commit rows with plain short SHAs. The sidecar wire
does not store commit URL bases.

Bead links resolve similarly, but from two sources with different trust. A bead id
recorded in the run's metadata is trusted lexically and always renders; it links
whenever the beads sidecar resolves to a hosted URL and otherwise degrades to a plain
bead id instead of a broken link. A bead id inferred from the agent's name is a guess
and only renders once it is confirmed against the local bead store. The sidecar wire
stores bead ids, not bead page URLs.

Published variables are the sanitized `sase var set KEY=VALUE` values stored in
`agent_meta.json["output_variables"]`. Variable names must match SASE's output-variable
identifier rule, while values may be any supported JSON scalar, list, or map. Nested map
keys are rendered in sorted order and list order is preserved. Table cells show bounded
inline previews; lists and maps also receive fenced YAML-shaped detail blocks below the
table. Values still use SASE's shared structural limits, including 8,192 UTF-8 bytes per
string leaf, depth and node caps, and a 65,536-byte encoded-value cap. They are visible
to anyone who can read the agents sidecar, so do not use output variables for secrets,
credentials, private tokens, or other sensitive values.

Neighbor rosters are sase-agent-scoped and owner-scoped. A sequential session is one
sase agent, and each session member page renders that session's roster. Rows mirror the
Agents tab's NEIGHBORS grouping: ancestors, descendants, then nearest hood groups, with
links to solo-agent pages, session pages, and the hood roster when a group is truncated.
Cross-owner and cross-machine relationships are intentionally excluded.

Compatibility note: snapshots published with `output_variables` metadata require readers
from this version or newer. Readers that understand the metadata key but predate
structured values may omit or reject non-string values; older strict v2 readers that do
not allow the metadata key fail loudly with `AgentsSyncFormatError` until they are
upgraded.

### Historical-name tolerance

Published history is treated as durable input, even when it contains an agent name that
current creation-time validation would reject. Read-side identity classification
therefore interprets `--<role>` as a session role only when it occurs in the final
dot-separated segment. For example, `4x--epic.f-0` is a solo name in hood `4x`, while
`fi--code.f0--code` is the `code` member of session `fi--code.f0` in hood `fi`.

Classification of a non-empty, path-safe historical name is best effort and must not
abort an inventory scan or hood publication. A record that is genuinely unsafe or cannot
be contained is excluded with its artifact path and reason in the publication
diagnostics. Historical records that share an old timestamp-derived run ID are assigned
distinct, deterministic IDs and reported instead of invalidating the hood. Stale session
metadata is likewise diagnosed and reconciled to the canonical name-derived
classification. If a linked primary commit for a _solo_ sase agent remains after its
local artifact has been cleaned up, publication synthesizes a minimal completed run from
the commit association so its `SASE_AGENT` page does not become a permanent dead link. A
session is never synthesized into a run: doing so would invent an
`agents/<session>/README.md` page next to the real session page, so those commits reach
the sidecar through the session container instead. When a session has commits that no
published container can carry, the history is reported in the publication diagnostics
rather than dropped silently. This read tolerance does not relax write validation: newly
generated solo, session, and clan names must still satisfy the current strict naming
rules.

## Commands and status

`sase agent sync` has separate mutating publication and read-only status modes.

Run a network publication reconciliation for all enabled projects:

```bash
sase agent sync
sase agent sync -p project-alias -p another-project
```

The repository transaction acquires a bounded lock, fetches and pulls with rebase,
publishes eligible locally owned hoods, restores deferred prompt archives, rebuilds
deterministic indexes, commits with the full owner identity, pushes, and drains queued
Referenced By work. Unfenced projects still refresh cited artifact sidecars. Fenced
projects convert leftover outbox rows into cites link events and never take those
sidecar locks. In inline commit mode, the commit workflow publishes the prompt archive
and records the resulting citations (legacy outbox or link events) before draining
agent-hood publication. In background mode, the durable hood request carries the prompt,
and the publisher records and drains its citations after the run's `done.json` exists or
the request is ten minutes old. In both modes, the prompt's agents-sidecar publication
completes before its back-reference drain begins. `sase agent sync` is the explicit
recovery command for queued requests a commit could not immediately resolve and the
full-reconciliation command for hoods with no recent commit. A non-fast-forward
rejection triggers one pull/recompute/commit/push retry. Conflicted rebases are aborted
and reported; a failure in one project does not prevent the others from running. The
Updates pane's `a` action is sase's TUI equivalent for all enabled projects.

Use `--json` to audit the complete schema-version-2 result. Each project reports the
legacy publication counters (`exported`, `export_refreshed`) plus v2 publication counts
(`hoods_published`, `hoods_refreshed`, `hoods_unchanged`, `agent_sessions_published`,
`runs_published`), push/commit state, and diagnostics. The default table is compact:
`V1` is the changed legacy-v1 publication count, and `HOODS` / `RUNS` report v2
publication totals.

Commit-triggered agent-hood publication uses a durable outbox at
`~/.sase/projects/<project-key>/agents-publication-outbox.json`, keyed by
`(global_agent, primary_revision)`. `primary_revision` is the commit the agent created
(the post-commit HEAD), not the workspace HEAD from before dispatch. A request for a
linked (non-primary) repository commit also records `scope: linked`; fulfillment then
requires only the agent's required publication page, because linked-repo SHAs never
appear in the run's primary `commit_shas`. Each request records its attempt count, most
recent attributable error, and quarantine or retirement state. Rows rekeyed by the
stale-revision repair keep their original requested revision in `requested_revision`
while `primary_revision` names the fulfilling commit; rows never repaired omit it, and
the original stays visible in doctor output and JSON. `publish_committed_agent_hood` is
the inline compatibility path: it enqueues the committing hood's request and immediately
drains every active request for the project under the bounded agents lock. The default
`commit.publication.mode: background` instead uses the enqueue-only path when axe is
running and the publisher heartbeat is no older than 15 minutes. It keeps bead-page
rendering, plan-header refresh, release evidence, and the durable enqueue on the commit
path, then the finalizer rings the publisher after writing `done.json`. If axe or the
publisher is unavailable, the commit uses the inline path. Setting
`commit.publication.mode` to `inline` always selects it. A failed durable enqueue keeps
`sase stitch create --resume` available. In either mode, every drain and full sync
rebuilds the archives owed by the requests it is about to acknowledge. A hood-specific
preparation failure increments only requests for that hood; repository-wide failures
such as lock contention, pull failure, or push failure remain retryable without
consuming unrelated per-item quarantine budgets. A repeatable failure that proves the
requested hood can never be published retires that request after one confirming retry
instead of quarantining it. Successful requests are acknowledged only after their
sidecar work is committed and safely pushed, or after the prepared payload is already
current.

The host-owned `publication` scheduler routine also drains active outbox requests. A
project doorbell under `~/.sase/projects/<project-key>/agent_publication/` starts the
fast path; a five-minute backstop catches a lost doorbell or hint. Hints prioritize
matching hood requests and name agents whose artifact-link rows should be drained in one
pass, while the durable outboxes remain the source of truth. Each pass has a four-minute
budget, writes queue counts and oldest request age to
`~/.sase/agent_publication/heartbeat.json`, and rings the doorbell again when retryable
work remains. `sase agent sync` remains the explicit full reconciliation path.

### Chats provenance versus publication

Chats calls a local transcript `shared` only when its `agents/<global-name>/chat.md`
path exists in the agents sidecar's committed tree. Dirty or partially prepared worktree
files do not count. Publication state is a separate dimension. Chats reports the outbox
disposition alongside provenance: a queued request is pending publication, a quarantined
request is paused but retryable, and a retired request is terminally unpublishable. A
chat can therefore be `shared` while a later revision is still queued or quarantined.
Retired requests remain in the outbox for review until they are explicitly dropped, but
they are neither pending nor quarantined.

Repeated hood-specific failures are quarantined after a bounded number of attempts.
Quarantined requests remain in the outbox, appear in sync/status `diagnostics` and
`quarantine_diagnostics`, and are skipped by ordinary drains. After fixing the reported
cause, explicitly reset and retry them:

```bash
sase agent sync --retry-quarantined -p project-alias
```

Do not delete or hand-edit either publication outbox. `--retry-quarantined` clears the
quarantine flag for both hood and Referenced By requests and gives them a fresh retry
budget before running the normal full reconciliation.

### Outbox diagnostics

`sase doctor -C state.agent_publication_outbox -j` reports a `last_error_histogram` that
groups requests by stable failure class (`timeout`, `lock_busy`, `index_lock`,
`unstaged_changes`, `rebase_conflict`, `manifest_mismatch`, `other`, `unknown`), the
oldest active request's age in `oldest_active_age_seconds`, a
`stale_requested_revision_count` of revision-scope rows whose requested revision is
absent from their published run's commits, and per-project hidden-clone state in
`sidecar_states` (commits ahead of/behind upstream, rebase in progress, untracked
`files/objects`, dirty `prompts/`/`artifacts/`). Every commit-triggered drain also
appends one structured timing line to `~/.sase/logs/agent_publication_drains.jsonl` with
per-stage durations and inventory counters; a failed drain names the sync-lock holder
(pid, operation, agent, age) recorded beside the lock file. Profile a representative
drain read-only with `tools/agents_publication_profile --project <key>`; see the
[publication internals](../../contribute/agents-sidecar-sync.md) for profiling and
repair procedures.

Retired agent-publication requests stay stopped until an explicit recovery. After a
publisher fix makes terminal work publishable, revive that project's retired hood
requests once with:

```bash
sase agent sync --retry-retired -p project-alias   # -t
```

`--retry-retired` requires `--project`, reports the selected count and prior failure
classes, and may be combined with `--retry-quarantined`. It does not touch the
Referenced By terminal queue, other projects, or requests that fail again during the
same command. It is rejected with `--check`, `--drop-retired`, and repair-only modes.

Use a bounded retry when you want to recover only a limited number of hood requests:

```bash
sase agent sync --retry-quarantined --retry-limit 10 -p project-alias
sase agent sync --retry-retired --retry-limit 5 --retry-error-class timeout -p project-alias
sase agent sync --retry-quarantined --retry-limit 1 --retry-error-class timeout \
  --retry-key 'alice.athena.worker@<full-sha>' -p project-alias
```

`--retry-limit N` requires either retry flag and exactly one `--project`. Add the
repeatable `--retry-error-class CLASS` filter to limit stopped requests to `timeout`,
`lock_busy`, `index_lock`, `unstaged_changes`, `rebase_conflict`, `manifest_mismatch`,
`unknown`, or `other`. A class filter requires `--retry-limit`. `--retry-key KEY` (`-k`)
retries exactly one request identified as `GLOBAL_AGENT@REVISION` with the full outbox
SHA; it requires `--retry-limit 1`, exactly one `--project`, and a retry lifecycle flag.
Inspect the current row before invoking. Missing, concurrently acknowledged or rekeyed,
or ineligible keys are bounded no-ops and never substitute another request. Commands
without `--retry-key` resume active requests first and keep their attempt counts;
remaining slots go to eligible retired requests before quarantined requests, oldest
first within each group. Only selected stopped requests receive a fresh attempt budget.
The limit counts requests, while each selected request publishes its complete hood.
Bounded retries do not reconcile other hoods, touch other projects, or drain the
Referenced By queue. After an interruption, selected requests stay active and are
prioritized on the next bounded invocation. The result reports selected, resumed,
revived, completed, and remaining request counts, and names the exact key when
`--retry-key` is set. Bounded retry cannot be combined with `--check`, `--refresh`,
`--drop-retired`, or either repair mode.

A retired request whose source still cannot be reconstructed should be dropped after
review, not revived. Drop only retired entries with:

```bash
sase agent sync --drop-retired -p project-alias
```

The command reports every removed hood or Referenced By request and its terminal reason,
then continues the normal full sync for the selected projects. `--drop-retired`,
`--retry-quarantined`, and `--retry-retired` mutate the outbox and are rejected with
`--check`.

Four repair modes replace the normal sync. Each reports what it changed:

```bash
sase agent sync --repair-digests -p project-alias   # -g
sase agent sync --repair-manifest -p project-alias  # -m
sase agent sync --repair-revisions -p project-alias # -R
sase agent sync --repair-states -p project-alias --state-limit 100 --json
```

Digest and manifest repair run under the same bounded lock and pull/commit/push
transaction and touch only the current owner's `users/<username>/machines/<machine>/`
files. Revision repair runs under the same bounded lock, operates on exactly one project
per call, reports by default, and writes only with `--apply`.

- `--repair-digests` handles a published file that was rewritten out of band, such as a
  hand-edited `chat.md`. It trusts the file on disk and re-signs the stale file
  references in that hood's snapshot, plus the owner-manifest digest that covers the
  snapshot. The `state.agent_publication_digest` check in `sase doctor` detects this
  drift and names the command.
- `--repair-manifest` restores owner-manifest entries for hood directories that exist on
  disk but are missing from the manifest, and normalizes stale explicit file lists to
  the supported slim entry. A stale list is repaired only after its snapshot digest and
  owner/project/hood identity, path safety, and every referenced file's size and digest
  are verified. Current and supported legacy lists are preserved; corrupt or unsafe
  candidates are skipped and reported. The command only reads and writes the current
  owner's subtree. Publication also refuses to start from a missing owner manifest while
  that owner's hood directories still exist, rather than republishing from an empty
  manifest.
- `--repair-revisions` maps stale pre-commit outbox revisions to the agent's committed
  revision without dropping any request. Each revision-scope row classifies as
  `unchanged`, `linked` (takes linked scope), `repaired` (the earliest recorded run
  commit descending from the requested revision replaces the row's key, keeping the
  original in `requested_revision`), or `unresolved` (kept exactly as is). Logical-key
  collisions merge deterministically. Lifecycle, attempts, and prior errors are never
  reset, and no row is revived, retried, or dropped. Apply mode appends every change to
  `agents-publication-repair-audit.jsonl` beside the outbox. The
  `state.agent_publication_outbox` check in `sase doctor` counts rows whose requested
  revision is absent from their published run's commits and names this command.
- `--repair-states` converges already-published runs to verified terminal state without
  a new commit. Preview reads the cached sidecar snapshot plus local evidence with no
  network, sidecar writes, audit writes, or checkpoint advancement. Apply refreshes
  upstream under the existing agents lock, rebuilds one bounded window, and publishes
  only state changes with regenerated pages. The window defaults to 100 examined runs
  across at most 5 hoods; `--state-limit` accepts 1 through 500 and `--state-after`
  resumes from a report's `next_cursor`. Preview is advisory: apply revalidates and may
  report different counts. The scheduler's `agent_state_refresh` job runs this repair
  once per tick for one project; see the owner-local backfill runbook in the sidecar
  internals.

CLI status checks maintain `~/.sase/agents_sync/status_snapshot.json`:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

Neither check mode imports agent history, publishes local hoods, changes the sidecar
worktree, commits, or pushes. Without `--refresh`, `--check` does not run Git or scan
local agent artifacts: it rewrites cached project status with publication outbox
diagnostics and carries forward recorded Git ahead/behind counts. Those counts can
therefore be absent or stale.

`--check --refresh` fetches remote refs and recomputes ahead and behind counts without
checking out remote content. `--refresh` is rejected unless `--check` is also present.
Use `--json` to inspect project state, cached ahead/behind counts, last fetch time,
errors, details, and publication `quarantine_diagnostics`.

## sase's TUI integration

sase's TUI does not detect, display, preview, or apply incoming agent imports. The
comprehensive `,U` Update panel covers SASE/core/plugins and providers only.

For an explicit full network publication/reconciliation, open SASE Admin Center's
Updates pane and press `a` (**Sync agents**). That tracked action covers every enabled
project, drains retryable agent-hood publication work, continues after project-local
failures, and refreshes the Agents view when it completes. It is equivalent to unscoped
`sase agent sync`. All Git, validation, publication, and full-sync work runs outside the
Textual event loop.

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- For an agent-hood outbox diagnostic, run `sase agent sync --check --json` and inspect
  the selected project's `quarantine_diagnostics`. The durable outbox file can also be
  read to correlate a request's `global_agent`, `primary_revision`, `attempts`, and
  `last_error`, but it must not be edited manually. Referenced By failures are reported
  by the mutating `sase agent sync` that tries to drain them; their durable
  `referenced-by-outbox.json` may likewise be inspected but not edited. If the local
  Referenced By commit succeeded and its detached push later failed, there is no
  remaining outbox entry; inspect the managed SDD sync log instead.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you
  intend to publish this scope.
- A malformed published v2 owner manifest, snapshot, or referenced digest is ignored
  while deterministic indexes are rebuilt; publication still validates the current
  owner's authority files before committing.
- If a published file differs from its recorded digest, run
  `sase agent sync --repair-digests -p <project>`. If publication reports on-disk hoods
  that the owner manifest omits, run `sase agent sync --repair-manifest -p <project>`.
- A queued agent-hood publication failure leaves the primary commit successful, with a
  warning naming the recovery command, and a durable retry request under the project's
  SASE state. Fix credentials/connectivity, then run `sase agent sync -p <project>` for
  an explicit drain, or make another commit — its inline drain retries every outstanding
  request for the project, not just its own. Repeating the original commit workflow does
  not create another primary commit.
- If an ordinary retry reports a quarantined publication request, fix the item-specific
  cause and run `sase agent sync --retry-quarantined -p <project>`. For a hood request,
  rerun `sase agent sync --check --json` afterward and confirm that no
  `quarantine_diagnostics` entry remains; for a Referenced By request, confirm that the
  mutating sync reports no remaining referenced-by diagnostic.
- A post-publication Referenced By failure currently reuses the generic warning that
  says prompt-archive publication was deferred. In this case that wording is misleading:
  the prompt archive was already pushed. Inspect the Referenced By diagnostic and outbox
  rather than republishing the primary commit.
- If a request is reported as retired after a publisher or validator fix, revive that
  project's retired hood requests with `sase agent sync --retry-retired -p <project>`
  (`-t`). Combine `--retry-quarantined` when quarantined work should move in the same
  pass. If the source truly cannot be reconstructed, review the terminal reason and run
  `sase agent sync --drop-retired -p <project>`. Retired requests are not reset by
  `--retry-quarantined` alone.
- A general push or fetch failure leaves local agent history intact. Fix
  credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. If it involves one
  unpublished replay commit against an advanced upstream, the
  [stale-replay recovery runbook](../../contribute/agents-sidecar-sync.md#stale-replay-recovery)
  describes the required preflight, backup, and explicit apply procedure. Other
  conflicts need review before retrying publication.

## Related

- [Agents and workspaces](index.md) — the section hub.
