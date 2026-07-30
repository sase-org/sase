# Agent Hood Synchronization

SASE publishes deterministic project-scoped agent-hood snapshots through each managed project's hidden `agents` sidecar.
The machine-level clone lives under `~/.sase/projects/<project-key>/repos/agents`; it is never exposed to launched
agents or copied into numbered workspaces.

## Privacy and configuration

One publication includes every locally owned active, waiting, terminal, failed, and dismissed run in the committing
agent's complete top-level hood. Active prompts can therefore appear before a transcript exists; later syncs can refresh
the stable run with terminal state, commits, or a readable chat. Portable metadata and family/clan relationships are
included as well. Creating or pushing the sidecar publishes that data to everyone who can read the configured remote.

Before running `sase repo init`, set the intrinsic `agents` sidecar's `visibility: private` when that scope must remain
restricted. Set `disabled: true` to opt out entirely. Synchronization never creates a remote and cannot bypass the
explicit consent requested by repository initialization.

Both the initial privacy-forward scaffold and the manifest-derived root browsing index display the same static
infographic. `sase repo init` owns `assets/agents-directory-map.png`: rerunning it creates or repairs the image without
replacing a populated sidecar's derived `README.md`. Agent synchronization owns only the dynamic publication paths.

Every publisher needs a complete selected `id.username` / `id.machine_name` owner identity. Local artifacts keep bare
semantic names such as `foo.bar--code`; v2 transport uses the canonical global name
`<username>.<machine_name>.foo.bar--code`. The exact owner manifest is the only shared authority file that publisher
mutates. Run `sase config init` to create or migrate the identity; see
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
```

An artifact reference such as `@agent:foo` or `@agent:<username>.<machine>.foo` addresses
`agents/<global-name>/README.md` in the selected project's agents sidecar. Local semantic names are accepted in the
current owner's context and canonicalized to the durable global name; published prompts, plans, and bead descriptions
should prefer the global spelling. Agent references do not accept `#L`, `#page=`, or `#t=` fragments. If the page has
not been published yet, run `sase agent sync` for the project before sharing the `@agent:` reference.

Owner manifests map each hood to the snapshot digest and its complete referenced-file set. Snapshot and per-run JSON is
strictly versioned, canonically encoded, size/count bounded, and content-addressed with SHA-256. Names and paths are
validated as single components, and every relationship/container batch passes through the Rust identity facade before
publication.

The allowlist excludes PIDs, workspace numbers, credentials, absolute paths, checkout paths, and other host-local
execution state. A publication is fully built and validated before rollback-safe atomic writes begin, so malformed input
cannot leave a half-rendered hood.

Existing top-level v1 `manifest.json` and `agents/<machine-qualified-name>` bundles are left untouched. Sync can still
read those records for compatibility, but it no longer creates or refreshes v1 transport data. `sase agent retire-v1` is
the only path that removes them, and only under the explicit evidence gate described in
[Legacy v1 limitations](#legacy-v1-limitations).

## Scope and reconciliation

Targeted publication refreshes exactly the committing agent's complete top-level hood. Full reconciliation publishes
every locally owned project hood with at least one primary-repository commit association. Commit-less plan members,
active siblings, failed/waiting runs, dismissed archives, and structural family/clan containers are included when they
belong to that hood.

After an agent-backed commit or pull-request operation records its first durable result marker, the commit workflow
resolves the project's agents target. When that target is available, SASE records an outbox request for the exact hood
before trying to publish it; the attempt also drains older queued publications for the project. A failure after the
request is queued does not roll back the primary VCS result, and the entry remains for a later commit or full sync. If
the target cannot be resolved, no outbox entry is guaranteed; a later full sync still publishes every locally eligible
hood. See [runtime provenance and publication](commit_workflows.md#cli-inputs-and-internal-payload).

Published runs that are temporarily missing from local inventory are retained. New terminal state, commits, prompt data,
and chat refresh the same stable run; absence does not create an implicit deletion or tombstone. Identical inputs
produce byte-identical files and a no-op publication.

After each pull/rebase, SASE rebuilds root, user, machine, hood, family, and agent Markdown from every validated owner
manifest. Family member links use stable `member-<role>` anchors; solo links target the corresponding agent README.
Because owners mutate disjoint authority files, a bounded non-fast-forward retry can pull a competing owner, recompute
the shared views, and converge without overwriting either snapshot.

## Browsing page anatomy

Root, user, machine, and hood pages stay focused on indexes. Agent and family pages carry the detailed artifact view for
one run or lane, and their optional sections keep a deterministic order so stable inputs produce byte-identical
Markdown.

An agent page uses this anatomy:

- Breadcrumb: root, user, machine, hood, optional family, and the current agent.
- Summary: model, provider, timing, commit count, and variable count when variables were published. Non-zero counts link
  to their page sections.
- Files: links to the published prompt and chat when each file exists.
- Commits: the run's commit table, when any commits were attributed to the run.
- Variables: sanitized output variables, when the run published any.
- Neighbors: related lanes in the same owner/machine hood, when the run's lane has any.

A family page keeps the `Lineage` diagram and accessible member table first, then uses the same optional artifact order:
`Commits`, `Variables`, and `Neighbors`. Family commit and variable tables include the member role so each row can be
traced back to a member. Family neighbor rows describe the family lane itself and never list its own members, which are
already present in the member table.

Commit cells link to hosted commit pages only when the project primary repository has a recognized GitHub remote. If the
primary remote is missing, not GitHub, or cannot be read, pages still render the same commit rows with plain short SHAs.
The sidecar wire does not store commit URL bases.

Published variables are the sanitized `sase var set KEY=VALUE` values stored in `agent_meta.json["output_variables"]`.
Only string keys matching SASE's output-variable identifier rule and string values are published. Values over the
8,192-byte UTF-8 limit are rejected by `sase var set` at write time rather than being silently dropped during
publication. They are visible to anyone who can read the agents sidecar, so do not use output variables for secrets,
credentials, private tokens, or other sensitive values.

Neighbor rosters are lane-scoped and owner-scoped. A sequential family is one lane, and each family member page renders
that family lane's roster. Rows mirror the Agents tab's NEIGHBORS grouping: ancestors, descendants, then nearest hood
groups, with links to solo-agent pages, family pages, and the hood roster when a group is truncated. Cross-owner and
cross-machine relationships are intentionally excluded.

Compatibility note: snapshots published with `output_variables` metadata require readers from this version or newer.
Older strict v2 readers that do not allow that metadata key fail loudly with `AgentsSyncFormatError` until they are
upgraded.

### Historical-name tolerance

Published history is treated as durable input, even when it contains an agent name that current creation-time validation
would reject. Read-side identity classification therefore interprets `--<role>` as a family role only when it occurs in
the final dot-separated segment. For example, `4x--epic.f-0` is a solo name in hood `4x`, while `fi--code.f0--code` is
the `code` member of family `fi--code.f0` in hood `fi`.

Classification of a non-empty, path-safe historical name is best effort and must not abort an inventory scan or hood
publication. A record that is genuinely unsafe or cannot be contained is excluded with its artifact path and reason in
the publication diagnostics. Historical records that share an old timestamp-derived run ID are assigned distinct,
deterministic IDs and reported instead of invalidating the hood. Stale family metadata is likewise diagnosed and
reconciled to the canonical name-derived classification. If a linked primary commit remains after its local artifact has
been cleaned up, publication synthesizes a minimal completed run from the commit association so its `SASE_AGENT` page
does not become a permanent dead link. This read tolerance does not relax write validation: newly generated solo,
family, and clan names must still satisfy the current strict naming rules.

## Importing shared history

A mutating sync also imports shared v2 hoods into local, project-scoped history. Each owner hood is an independent
package. Before writing local state, SASE validates its owner manifest, snapshot and referenced-file digests, bounded
paths and payloads, portable metadata, relationship graph, and permanent-name claims. A malformed owner or hood is
reported as quarantined and is not imported; validation can continue for unrelated packages.

A valid remote run becomes a terminal historical artifact and dismissed-agent bundle, not a live process. Source
`active`, `waiting`, and `stopped` states appear locally as `STOPPED`; a source failure remains `FAILED`; other terminal
states appear as `DONE`. Available prompts, chats, commits, restart metadata, and family/clan/wait/retry relationships
are retained. A sequential family is also recorded as one stable saved-family group, so the normal ACE family-revival
flow can relaunch it directly: press `R` in the Agents tab and choose the group labeled **Agents sidecar**. The preview
retains role order, parent mapping, raw prompts, model/provider/reasoning settings, and conditional localized names.
Refreshing that family preserves its existing revival timestamp and count.

Imports are transactional per hood. SASE prepares the complete local artifact, dismissed bundle, saved-family record,
and permanent-name claims as a staged transaction, then applies and finalizes it under a project import lock. Loaders
ignore a transaction until it is complete. A later v2 import pass discards an interrupted prepared transaction or
finishes one that had begun applying. Re-importing the same snapshot is a no-op; a new digest refreshes the existing
imported records. When the package describes the current owner and SASE can match a local run by durable ID or primary
commit evidence, it treats that run as already observed instead of creating a duplicate.

## Commands and status

There are three deliberately separate modes.

Run a full-duplex network reconciliation for all enabled projects:

```bash
sase agent sync
sase agent sync -p project-alias -p another-project
```

The repository transaction acquires a bounded lock, fetches and pulls with rebase, imports validated shared v2 history
and optional legacy v1 bundles, drains commit-publication outbox entries, performs v2 publication for locally owned
hoods, rebuilds deterministic indexes, commits with the full owner identity, and pushes. A non-fast-forward rejection
triggers one pull/recompute/commit/push retry. Conflicted rebases are aborted and reported; a failure in one project
does not prevent the others from running. Import preflight indexes local artifacts once per project sync and reuses that
view across every incoming hood and run. Exact-owner preflight also indexes matching `SASE_AGENT` commit evidence across
local project checkouts, so cleaned runs are observed instead of re-imported. Interrupted transaction recovery runs once
per project pass, v1 compatibility lookup scans artifacts once, and imported dismissed bundles update their summary
index incrementally. The Updates pane's `a` action is the ACE equivalent for all enabled projects.

Use `--json` to audit the complete schema-version-2 result. In addition to the legacy `integrated`, `refreshed`,
`exported`, and `export_refreshed` fields, each project reports `hoods_imported`, `hoods_import_refreshed`,
`hoods_import_unchanged`, `hoods_quarantined`, `families_imported`, and `runs_imported`, plus the corresponding v2
publication counts and diagnostics. The default table is intentionally compact: `IMPORTED` is the changed legacy-v1
import count, `V1` is the changed legacy-v1 publication count, and `HOODS` / `RUNS` report v2 publication—not v2 import—
totals. ACE's tracked-task lines likewise do not currently include the v2 import fields, so a project that only imports
or refreshes v2 history can be summarized there as `current`; use the CLI's `--json` result to audit those imports.

Commit-triggered publications use a durable outbox at `~/.sase/projects/<project-key>/agents-publication-outbox.json`.
Each request records its agent, primary revision, top-level hood, attempt count, most recent attributable error, and
quarantine or retirement state. A hood-specific preparation failure increments only requests for that hood;
repository-wide failures such as lock contention, pull failure, or push failure remain retryable without consuming the
per-item quarantine budget. A repeatable failure that proves the requested hood can never be published retires that
request after one confirming retry instead of quarantining it. Successful requests are acknowledged only after the
sidecar commit is safely pushed (or the prepared payload is already current) and the requested agent page exists in the
sidecar.

### Chats provenance versus publication

Chats calls a local transcript `shared` only when its `agents/<global-name>/chat.md` path exists in the agents sidecar's
committed tree. Dirty or partially prepared worktree files do not count. Publication state is a separate dimension.
Chats reports the outbox disposition alongside provenance: a queued request is pending publication, a quarantined
request is paused but retryable, and a retired request is terminally unpublishable. A chat can therefore be `shared`
while a later revision is still queued or quarantined. Retired requests remain in the outbox for review until they are
explicitly dropped, but they are neither pending nor quarantined.

Repeated hood-specific failures are quarantined after a bounded number of attempts. Quarantined requests remain in the
outbox, appear in sync/status `diagnostics` and `quarantine_diagnostics`, and are skipped by ordinary drains. After
fixing the reported cause, explicitly reset and retry them:

```bash
sase agent sync --retry-quarantined -p project-alias
```

Do not delete or hand-edit the outbox. `--retry-quarantined` clears the quarantine flag and gives those requests a fresh
retry budget before running the normal full reconciliation.

A retired request cannot succeed on retry. After reviewing the diagnostic and accepting that its missing or invalid
source cannot be reconstructed, drop only retired entries with:

```bash
sase agent sync --drop-retired -p project-alias
```

The command reports every removed request and its terminal reason, then continues the normal full sync for the selected
projects. Both `--drop-retired` and `--retry-quarantined` mutate the outbox and are rejected with `--check`.

Periodic detection and the equivalent CLI status checks maintain `~/.sase/agents_sync/status_snapshot.json` and
validated incoming-hood cache objects:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

Neither check mode imports agent history, publishes local hoods, changes the sidecar worktree, commits, or pushes.
Without `--refresh`, `--check` does not run Git or scan local agent artifacts: it reconciles persisted incoming-hood
entries against import receipts and rewrites the status snapshot while carrying forward previously recorded Git counts.
Those diagnostic counts can therefore be absent or stale.

`--check --refresh` is the networked detection path. It fetches remote refs, validates the fetched agents commit without
checking it out, stores independently valid incoming hoods from other owners in the local incoming cache, and recomputes
ahead and behind counts. Exact-current-owner hoods — including owner-observed legacy v1 groups — are observed but do not
become pending updates. `--refresh` is rejected unless `--check` is also present. Use `--json` to inspect cached
`pending_updates`, quarantine diagnostics, and the fetched ref and commit.

## ACE integration

ACE performs a networked detection check after first paint and then checks enabled agents repositories periodically. The
green `⇅ N` badge counts only validated incoming hoods from other owners already captured in the incoming cache and not
covered by an import receipt. Same-user/other-machine and other-user/same-machine hoods are incoming from another owner;
exact-current-owner changes are not. Local ahead work, missing or disabled sidecars, Git behind counts, and errors
remain available in CLI diagnostics but do not light the badge.

Hover the badge for the project, source owner, hood, run, and family counts represented by that immutable snapshot.
Clicking it imports exactly those displayed cache items as a tracked task. That path does not fetch, pull, push, export,
or mutate the sidecar checkout; successful receipts clear the corresponding badge entries. The `,U` comprehensive update
preview likewise captures only the cache items visible when the preview is built, lists their exact project and hood
counts under **Agents repos**, and imports them after its other legs without network access. A later periodic fetch
cannot widen an already confirmed preview.

For an explicit full network reconciliation, open SASE Admin Center's Updates pane and press `a` (**Sync agents**). That
tracked action covers every enabled project, drains publication retries, continues after project-local failures, and
refreshes the agent list, status, badge, and indexes when it completes. It is equivalent to unscoped `sase agent sync`,
not to clicking the badge or running `,U`.

Configure that status loop under `ace.agents_sync`. By default, ACE reconciles cached entries and receipts every 10
minutes and, once at least 30 minutes have elapsed, performs the remote-fetching detection pass on the next status tick.
All Git, validation, cache import, and full-sync work runs outside the Textual event loop. See
[ACE agents-sync configuration](configuration.md#aceagents_sync).

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- For an outbox diagnostic, run `sase agent sync --check --json` and inspect the selected project's
  `quarantine_diagnostics`. The durable outbox file can also be read to correlate a request's `global_agent`,
  `primary_revision`, `attempts`, and `last_error`, but it must not be edited manually.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you intend to publish this scope.
- A malformed legacy v1 manifest is quarantined and skipped with a diagnostic. A malformed v2 owner manifest, snapshot,
  or referenced digest is quarantined from import; full v2 publication still validates all shared authority and may fail
  that project's reconciliation rather than overwrite corrupt data.
- An interrupted v2 local import stays invisible until complete. A subsequent v2 import pass performs journal recovery;
  in the normal case, rerunning a mutating sync supplies that pass. Use `--json` to inspect recovery or quarantine
  diagnostics.
- A post-commit sidecar push failure leaves the primary commit successful and a durable retry request under the
  project's SASE state. Fix credentials/connectivity and run `sase agent sync -p <project>` (or Updates-pane `a`) to
  drain it. Repeating the original commit workflow does not create another primary commit.
- If an ordinary retry reports a quarantined publication request, fix the item-specific cause and run
  `sase agent sync --retry-quarantined -p <project>`. Rerun `sase agent sync --check --json` afterward and confirm that
  no publication quarantine diagnostic remains.
- If a request is reported as retired and its source truly cannot be reconstructed, review the terminal reason and run
  `sase agent sync --drop-retired -p <project>`. Retired requests are not reset by `--retry-quarantined`.
- A general push or fetch failure leaves local agent history intact. Fix credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected state in the hidden clone, then rerun
  `sase agent sync`.

## Legacy v1 limitations

V1's top-level manifest and `agents/<machine-qualified-name>` files remain in place and read-only. A v1 row has no
trustworthy username owner. SASE therefore treats it as foreign/unknown by default, imports it through the compatibility
path when valid, and never republishes it as locally owned v2 data. A shared machine token alone is never proof of
ownership, and v1 cannot reconstruct the complete transactional family and relationship state guaranteed by v2.

### Owner-observed v1 groups

A v1 manifest group whose machine token matches the current owner's machine is reclassified as **owner-observed** — this
machine's own history rather than incoming work — when either kind of first-party evidence holds:

- the current owner's v2 manifest already publishes that hood, or
- an entry in the group matches a local non-imported artifact by timestamp and machine-qualified name and shares a
  commit SHA, compared with prefix-aware equivalence so an abbreviated local marker matches a full sidecar SHA.

Owner-observed groups count as exact-owner, never enter the incoming cache, never light the badge, and are recorded
`unchanged` instead of imported. Both the cached `,U` leg and full sync share that verdict, neither writes an import
receipt for such a group, and the name registry rejects an owner-machine legacy claim as a backstop. Everything else
stays foreign, including any v1 group on a different machine and any same-machine group with no evidence.

### Retiring this machine's v1 payload

`sase agent retire-v1` removes the current machine's legacy-v1 payload once the owner's v2 manifest fully covers it:

```bash
sase agent retire-v1
sase agent retire-v1 -p project-alias --json
sase agent retire-v1 --apply
```

It is a dry run unless `--apply` is supplied, refuses and prints the uncovered hoods when any current-machine v1 hood is
missing from the owner's v2 manifest, and removes only this machine's rows — another machine's v1 entries and bundles
are left in place. `--apply` commits and pushes through the same locked sync transaction as ordinary publication, and
Git history keeps the removed payload recoverable.
