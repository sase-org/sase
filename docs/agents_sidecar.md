# Agent Hood Synchronization

SASE publishes deterministic project-scoped agent-hood snapshots and canonical prompt
archives through each managed project's hidden `agents` sidecar. The machine-level clone
lives under `~/.sase/projects/<project-key>/repos/agents`; it is never exposed to
launched agents or copied into numbered workspaces.

## Privacy and configuration

One publication includes every locally owned active, waiting, terminal, failed, and
dismissed run in the committing agent's complete top-level hood. Active prompts can
therefore appear before a transcript exists; later syncs can refresh the stable run with
terminal state, commits, or a readable chat. Portable metadata and family/clan
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
[owner identity and machine overlays](configuration.md#owner-identity).

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
families/<global-family>.md
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

Owner manifests map each hood to the snapshot digest and its complete referenced-file
set. Snapshot and per-run JSON is strictly versioned, canonically encoded, size/count
bounded, and content-addressed with SHA-256. Names and paths are validated as single
components, and every relationship/container batch passes through the Rust identity
facade before publication.

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

- A normal commit publication uses `raw_xprompt.md`: SASE has resolved project and
  configured xprompt aliases, but has not expanded the xprompts. Reusable `#...`
  references therefore remain visible.
- An approved planner publication uses the plan snapshot: xprompts and workflow
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

Prompt-archive publication is not a separate durable queue. The commit path publishes
the archive directly, and the outbox request enqueued for that commit's hood also owns
its prompt: when the archive cannot be written right away — the agents lock is busy, for
instance — the next drain or full `sase agent sync` regenerates it from the local
artifact pool inside the same bounded transaction that publishes the hood. A request is
acknowledged only once both halves reached the sidecar, so a prompt that could not be
rebuilt keeps its request queued and retryable rather than retiring it.

Document back-references are separate. Only after publishing a prompt archive that
contains a provider-document reference does SASE record a request in
`~/.sase/projects/<project-key>/referenced-by-outbox.json` and try to update the cited
artifact sidecar's managed `Referenced By` table. This drain attempt runs before the
publishing command returns, but it cannot delay or roll back the prompt publication that
already completed. A request stays queued when the artifact-sidecar pull, update, or
local commit fails. Once the local refresh succeeds, SASE acknowledges the request; if
it created a commit, SASE starts that commit's push asynchronously. A later push failure
is recorded in the managed SDD sync log rather than restored to this outbox. Queued
requests use the same retry, quarantine, and retired-entry operator controls as hood
publication. See [Artifact Reference Publication](artifact_references.md#publication)
for the complete ordering and recovery boundary.

Use `sase agent prompts list` to browse the archive. `sase agent prompts show <prompt>`
prints the archived Markdown document. `sase agent prompts validate` verifies headers,
artifact links, digest-bearing filenames, local manifests, and plan cross-links.
`sase agent prompts migrate` reports historical plans-sidecar prompts by default and
moves them to this archive only with `--write`.

Existing top-level v1 `manifest.json` and `agents/<machine-qualified-name>` bundles are
left untouched. Sync can still read those records for compatibility, but it no longer
creates, refreshes, imports, or retires v1 transport data. Historical local imports can
still be removed with `sase agent names forget-import` when their full legacy closure is
superseded.

## Scope and reconciliation

Targeted publication refreshes exactly the committing agent's complete top-level hood.
Full reconciliation publishes every locally owned project hood with at least one
primary-repository commit association. Commit-less plan members, active siblings,
failed/waiting runs, dismissed archives, and structural family/clan containers are
included when they belong to that hood.

After an agent-backed commit or pull-request operation records its first durable result
marker, the commit workflow resolves the project's agents target. When that target is
available, SASE records an outbox request for the exact hood and immediately drains it
under the bounded agents lock, so the commit does not return until the hood is published
and pushed (or the request is confirmed queued for retry). A publication that cannot
even be queued fails the commit with a `sase stitch create --resume` hint; a request
that survives the immediate drain — because of a transient, hood-specific, or
repository-wide failure — prints a warning naming the recovery command and is retried by
a later commit's drain or by an explicit `sase agent sync`. See
[runtime provenance and publication](commit_workflows.md#cli-inputs-and-internal-payload).

Published runs that are temporarily missing from local inventory are retained. New
terminal state, commits, prompt data, and chat refresh the same stable run; absence does
not create an implicit deletion or tombstone. Identical inputs produce byte-identical
files and a no-op publication.

After each pull/rebase, SASE rebuilds root, user, machine, hood, family, and agent
Markdown from every validated owner manifest. Index and neighbor pages link a _specific
run_, so their family member links use stable `member-<role>` anchors; solo links target
the corresponding agent README. Commit footers are the other case: they identify a sase
agent rather than a run, so they link the family page with no member anchor (see
[runtime provenance](commit_workflows.md#cli-inputs-and-internal-payload)). Because
owners mutate disjoint authority files, a bounded non-fast-forward retry can pull a
competing owner, recompute the shared views, and converge without overwriting either
snapshot.

## Browsing page anatomy

Root, user, machine, and hood pages stay focused on indexes. Agent and family pages
carry the detailed artifact view for one run or lane, and their optional sections keep a
deterministic order so stable inputs produce byte-identical Markdown.

An agent page uses this anatomy:

- Breadcrumb: root, user, machine, hood, optional family, and the current agent.
- Summary: bead and epic links when the run is associated with a bead, above model,
  provider, timing, commit count, and variable count when variables were published.
  Non-zero counts link to their page sections.
- Files: links to the published prompt and chat when each file exists.
- Commits: the run's commit table, when any commits were attributed to the run.
- Variables: sanitized output variables, when the run published any.
- Neighbors: related sase agents in the same owner/machine hood, when any exist.

A family page keeps the `Lineage` diagram and accessible member table first, then uses
the same optional artifact order: `Commits`, `Variables`, and `Neighbors`. Family commit
and variable tables include the member role so each row can be traced back to a member.
Family neighbor rows describe the family itself and never list its own members, which
are already present in the member table.

The family page is the durable home of a family's commits. Because a commit footer names
the sase agent rather than the member, family commit history is owned by the family
container itself and is carried in the published snapshot alongside the per-member rows.
The `Commits` table unions both sources: rows recovered from a member's own artifact
keep that member's role, and sase-agent-level rows — including commits whose member
artifact has since been cleaned up — render with a `—` role. Rows are deduplicated by
SHA with the member-attributed row winning, then sorted and capped like every other
commit table. Clan containers never accumulate commits this way; only families do.

When any member is associated with a bead, the family header line also names the
distinct bead ids across the family's members after `Members:` — one as `Bead: <link>`,
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

Neighbor rosters are sase-agent-scoped and owner-scoped. A sequential family is one sase
agent, and each family member page renders that family's roster. Rows mirror the Agents
tab's NEIGHBORS grouping: ancestors, descendants, then nearest hood groups, with links
to solo-agent pages, family pages, and the hood roster when a group is truncated.
Cross-owner and cross-machine relationships are intentionally excluded.

Compatibility note: snapshots published with `output_variables` metadata require readers
from this version or newer. Readers that understand the metadata key but predate
structured values may omit or reject non-string values; older strict v2 readers that do
not allow the metadata key fail loudly with `AgentsSyncFormatError` until they are
upgraded.

### Historical-name tolerance

Published history is treated as durable input, even when it contains an agent name that
current creation-time validation would reject. Read-side identity classification
therefore interprets `--<role>` as a family role only when it occurs in the final
dot-separated segment. For example, `4x--epic.f-0` is a solo name in hood `4x`, while
`fi--code.f0--code` is the `code` member of family `fi--code.f0` in hood `fi`.

Classification of a non-empty, path-safe historical name is best effort and must not
abort an inventory scan or hood publication. A record that is genuinely unsafe or cannot
be contained is excluded with its artifact path and reason in the publication
diagnostics. Historical records that share an old timestamp-derived run ID are assigned
distinct, deterministic IDs and reported instead of invalidating the hood. Stale family
metadata is likewise diagnosed and reconciled to the canonical name-derived
classification. If a linked primary commit for a _solo_ sase agent remains after its
local artifact has been cleaned up, publication synthesizes a minimal completed run from
the commit association so its `SASE_AGENT` page does not become a permanent dead link. A
family is never synthesized into a run: doing so would invent an
`agents/<family>/README.md` page next to the real family page, so those commits reach
the sidecar through the family container instead. When a family has commits that no
published container can carry, the history is reported in the publication diagnostics
rather than dropped silently. This read tolerance does not relax write validation: newly
generated solo, family, and clan names must still satisfy the current strict naming
rules.

## Shared History Import Retirement

`sase agent sync` no longer imports remote hoods into local agent history. The agents
sidecar remains the publication and browsing surface for each owner's exported hoods,
and existing imported local records remain readable until they are explicitly removed by
the supported legacy-import cleanup commands. Status checks likewise report sidecar Git
state and publication diagnostics only; they do not maintain an incoming-hood cache.

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
Referenced By requests into their artifact sidecars. The commit workflow has a separate
earlier prompt-archive step: it publishes that archive and drains the resulting
back-reference requests before it proceeds to agent-hood publication. In both cases, the
prompt's agents-sidecar publication completes before its back-reference drain begins.
`sase agent sync` is the explicit recovery command for queued requests a commit could
not immediately resolve and the full-reconciliation command for hoods with no recent
commit. A non-fast-forward rejection triggers one pull/recompute/commit/push retry.
Conflicted rebases are aborted and reported; a failure in one project does not prevent
the others from running. The Updates pane's `a` action is the ACE equivalent for all
enabled projects.

Use `--json` to audit the complete schema-version-2 result. Each project reports the
legacy publication counters (`exported`, `export_refreshed`) plus v2 publication counts
(`hoods_published`, `hoods_refreshed`, `hoods_unchanged`, `families_published`,
`runs_published`), push/commit state, and diagnostics. The default table is compact:
`V1` is the changed legacy-v1 publication count, and `HOODS` / `RUNS` report v2
publication totals.

Commit-triggered agent-hood publication uses a durable outbox at
`~/.sase/projects/<project-key>/agents-publication-outbox.json`, keyed by
`(global_agent, primary_revision)`. Each request records its attempt count, most recent
attributable error, and quarantine or retirement state. `publish_committed_agent_hood`
enqueues the committing hood's request and immediately drains every active request for
the project under the bounded agents lock, so a healthy commit publishes and pushes
before it returns. Bead-page rendering and plan-header refresh are separate synchronous
steps on the commit path. Prompt-archive publication is attempted synchronously too, but
its retry obligation is covered by the hood request: every drain and full sync rebuilds
the archives owed by the requests it is about to acknowledge. A prompt archive that
cannot even be queued fails the commit with a `sase stitch create --resume` hint, the
same way an unqueueable hood does. A hood-specific preparation failure increments only
requests for that hood; repository-wide failures such as lock contention, pull failure,
or push failure remain retryable without consuming unrelated per-item quarantine
budgets. A repeatable failure that proves the requested hood can never be published
retires that request after one confirming retry instead of quarantining it. Successful
requests are acknowledged only after their sidecar work is committed and safely pushed,
or after the prepared payload is already current.

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

A retired request cannot succeed on retry. After reviewing the diagnostic and accepting
that its missing or invalid source cannot be reconstructed, drop only retired entries
with:

```bash
sase agent sync --drop-retired -p project-alias
```

The command reports every removed hood or Referenced By request and its terminal reason,
then continues the normal full sync for the selected projects. Both `--drop-retired` and
`--retry-quarantined` mutate the outbox and are rejected with `--check`.

CLI status checks maintain `~/.sase/agents_sync/status_snapshot.json`:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

Neither check mode imports agent history, publishes local hoods, changes the sidecar
worktree, commits, or pushes. Without `--refresh`, `--check` does not run Git or scan
local agent artifacts: it rewrites cached project status with publication outbox
diagnostics and carries forward previously recorded Git ahead/behind counts. Those
counts can therefore be absent or stale.

`--check --refresh` fetches remote refs and recomputes ahead and behind counts without
checking out remote content. `--refresh` is rejected unless `--check` is also present.
Use `--json` to inspect project state, cached ahead/behind counts, last fetch time,
errors, details, and publication `quarantine_diagnostics`.

## ACE integration

ACE does not detect, display, preview, or apply incoming agent imports. The
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
- If a request is reported as retired and its source truly cannot be reconstructed,
  review the terminal reason and run `sase agent sync --drop-retired -p <project>`.
  Retired requests are not reset by `--retry-quarantined`.
- A general push or fetch failure leaves local agent history intact. Fix
  credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected state in
  the hidden clone, then rerun `sase agent sync`.

## Legacy v1 limitations

V1's top-level manifest and `agents/<machine-qualified-name>` files remain in place and
read-only. A v1 row has no trustworthy username owner, a shared machine token alone is
never proof of ownership, and v1 cannot reconstruct the complete transactional family
and relationship state guaranteed by v2. Current sync and status commands do not import
or retire v1 transport data. Already-imported local legacy history can be removed with
`sase agent names forget-import` after the command confirms the import closure is fully
superseded.
