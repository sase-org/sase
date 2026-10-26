---
title: Agent sidecar synchronization internals
description: Synchronization and reconciliation internals for agent sidecars.
---

# Agent sidecar synchronization internals

This page documents the implementation boundaries behind agent sidecar synchronization.

## Scope and reconciliation

Targeted publication refreshes exactly the committing agent's complete top-level hood.
Full reconciliation publishes every locally owned project hood with at least one
primary-repository commit association. Commit-less plan members, active siblings,
failed/waiting runs, dismissed archives, and structural session/clan containers are
included when they belong to that hood.

After an agent-backed commit or pull-request operation records its first durable result
marker, the commit workflow resolves the project's agents target. When that target is
available, SASE records an outbox request for the exact hood at the created commit SHA
and immediately drains it under the bounded agents lock, so the commit does not return
until the hood is published and pushed (or the request is confirmed queued for retry). A
linked-repo commit uses the same host-project outbox with `scope: linked`, so
acknowledgment requires the published page rather than a primary-revision match. A
publication that cannot even be queued fails the commit with a
`sase stitch create --resume` hint; a request that survives the immediate drain —
because of a transient, hood-specific, or repository-wide failure — prints a warning
naming the recovery command and is retried by a later commit's drain or by an explicit
`sase agent sync`. See
[runtime provenance and publication](commit-workflow-orchestrator.md#cli-inputs-and-internal-payload).

Published runs that are temporarily missing from local inventory are retained. New
terminal state, commits, prompt data, and chat refresh the same stable run; absence does
not create an implicit deletion or tombstone. Identical inputs produce byte-identical
files and a no-op publication.

Commit-triggered drains emit one structured timing line per drain to
`~/.sase/logs/agent_publication_drains.jsonl` (see
`src/sase/agents_sync/publication_timing.py`), recording lock wait, per-stage durations,
inventory counters, and per-op git subprocess counts. `bounded_agents_lock` records its
holder (`{pid, operation, agent, started_at}`) beside the flock file so lock-busy errors
name the holder and its age. The drain transaction accepts an optional `DrainTiming`
accumulator; without one every code path behaves exactly as before.

After each pull/rebase, SASE rebuilds root, user, machine, hood, session, and agent
Markdown from every validated owner manifest. Index and neighbor pages link a _specific
run_, so their session member links use stable `member-<role>` anchors; solo links
target the corresponding agent README. Commit footers are the other case: they identify
a sase agent rather than a run, so they link the session page with no member anchor (see
[runtime provenance](commit-workflow-orchestrator.md#cli-inputs-and-internal-payload)).
Because owners mutate disjoint authority files, a bounded non-fast-forward retry can
pull a competing owner, recompute the shared views, and converge without overwriting
either snapshot.

## Bounded outbox retries

`sase agent sync --retry-limit` selects one project's request batch while holding the
publication outbox lock. The Rust recovery selector places existing active requests
first, then chooses eligible retired requests before quarantined requests, oldest first
within each group with a logical-key tie break. An error-class filter applies only to
stopped requests. The atomic outbox update revives only selected stopped rows and
records their prior errors in diagnostics before clearing them. Active rows retain their
attempt history.

`--retry-key GLOBAL_AGENT@REVISION` constrains that same selector to one outbox
identity. The revision must be the full SHA stored on the row. Inspect the current
lifecycle, error class, and protection status before invoking: a prior preview is not
authorization to ignore current state at mutation time. A missing, concurrently
acknowledged or rekeyed, or ineligible key is a bounded no-op and never substitutes
another request. Commands without `--retry-key` keep the active-first then
retired-before-quarantined selection above.

The selected logical keys flow unchanged into the targeted publication transaction. That
transaction builds complete selected hoods, but acknowledges only selected requests and
does not run full reconciliation or the Referenced By drain. The request limit is
therefore not a byte or run cap; the existing 120-second transaction bound still
applies. If interrupted, the selected rows remain active, so the next bounded invocation
resumes them before selecting more stopped work. Unbounded retry flags keep their
full-sync behavior.

## Owner-manifest repair

`sase agent sync --repair-manifest` repairs only the current owner's manifest and hood
directories. It restores entries for snapshots that have no manifest entry and repairs a
stale explicit `files` list by dropping that redundant list into the supported slim
form. Before changing a stale entry, the command verifies the snapshot digest and owner,
project, and hood identity, asks the Rust session-manifest policy to validate paths, and
checks every referenced payload's byte count and digest. Counts come from the verified
snapshot. Current and supported legacy explicit lists remain unchanged; unsafe lists,
identity or digest mismatches, and missing or corrupt payloads are reported and skipped.
The command never reads or changes another owner's subtree, preserves the snapshot and
payload bytes, and becomes a no-op after a successful repair.

## Stale-revision repair

`sase agent sync --repair-revisions` repairs rows enqueued before the post-commit
revision fix: they name a pre-commit primary revision no published run carries, so they
never acknowledge. The repair classifies each revision-scope row against the agent's
local run records and primary-repo ancestry, then rekeys, re-scopes, or keeps it:

- `unchanged`: the requested revision is already among the agent's run commits, or the
  row already carries linked scope. Nothing changes.
- `linked`: the requested revision is a linked-repo commit. The row takes linked scope
  and fulfills when the required page exists.
- `repaired(S)`: S is the earliest recorded run commit descending from the requested
  revision. The row is rekeyed to S; the original stays in `requested_revision`, so the
  ack gate and deferred prompt restore use S while doctor and JSON output still show the
  original.
- `unresolved`: no evidence. The row is kept exactly as it is.

Logical-key collisions from rekeying merge deterministically into one row and the merge
is recorded. Lifecycle, attempts, and prior errors are kept; the repair never revives,
retries, or drops a row.

Run one project per call, in report-then-apply order, then retry the bounded backlog:

```bash
sase agent sync --repair-revisions -p project-alias         # report only
sase agent sync --repair-revisions -p project-alias --apply # write + audit
```

Report mode writes nothing: no outbox rewrite and no audit file. Apply mode rewrites the
outbox only through the outbox mutation APIs under the agents-sync lock and appends one
JSON object per applied change to
`~/.sase/projects/<project-key>/agents-publication-repair-audit.jsonl` (old key, new
revision or scope, evidence commit, and time). A second apply is a no-op.

## Stale-replay recovery

This is a finite recovery helper for a sidecar that is one unpublished commit ahead of a
remote that has also moved. It is not part of a normal drain. Use it when a local HEAD
(historically Apollo bob-cli `2abeff3f9`) cannot rebase onto upstream because stale
derived pages conflict, while unique owner snapshots, chats, and `files/objects` blobs
still need to be published.

Work only in the hidden machine clone from `sase repo open`. Do not reset a primary
nested sidecar. The helper acquires the existing agents-sync lock, fetches, and rechecks
HEAD before it writes anything into the backup directory.

### Preconditions

- The project's hidden agents clone exists and has an upstream.
- Local `HEAD` is the unpublished replay you intend to discard after backup. Pass that
  SHA as `--expected-head` (full or unique prefix).
- `--backup-dir` is an empty directory outside the clone. The helper refuses to reuse a
  backup that belongs to a different HEAD.
- Unique owner content lives in snapshots, `agents/*/chat.md` / `prompt.md`, and
  untracked `files/objects/sha256/<xx>/<digest>` blobs. Browsing pages (`README.md`,
  session pages, and hood README files) are treated as regenerable.

### Commands

Report first. This inventories unpublished paths, classifies them through
`sase_core_rs`, writes a verified bundle of `@{upstream}..HEAD`, copies owner content
and pending objects, and records checksums plus `revisions.json`. It does not reset or
publish:

```bash
.venv/bin/python tools/agents_publication_recover_replay \
    --project bob-cli \
    --expected-head 2abeff3f9 \
    --backup-dir /tmp/bob-cli-replay
```

Inspect the JSON report: `ahead` / `behind`, `owner_content_paths`,
`archive_object_paths`, `unknown_paths`, and `refused_divergences`. `stage` must be
`verified`. Confirm `revisions.json` names the expected HEAD and that every checksum
other than `progress.json` matches. If `unknown_paths` or `refused_divergences` is
non-empty, stop. Same-run content is compared as bytes. When a merge-base version
exists, recovery keeps the side that changed while the other side still matches the
base; two-sided non-prefix changes are refused. Without a merge-base version, the
existing identical, empty, and prefix rules apply. The backup stays intact on refusal.

Apply with the same backup directory and the same expected HEAD. Apply refuses before
mutation when HEAD moved, the backup checksums fail, or content cannot be reconciled:

```bash
.venv/bin/python tools/agents_publication_recover_replay \
    -p bob-cli -H 2abeff3f9 -b /tmp/bob-cli-replay --apply
```

Apply aborts any rebase, `git reset --hard @{upstream}`, restores pending objects, then
republishes preserved hoods through `sync_project_locked`. Browsing pages are rebuilt
from the merged owner snapshot. Unique runs from both the unpublished commit and current
upstream are kept. `files/objects` is never cleaned.

Rerunning `--apply` with the same backup resumes an interrupted mutation (`stage`
`reset` or `replaying`) without rewriting the backup, and reports `already_complete`
once `stage` is `complete`.

### Postconditions

- Sidecar `HEAD` is a descendant of the fetched upstream, with unique local chats,
  session members, and pending objects committed and pushed.
- Remote `load_validated_publication` succeeds. Owner-manifest `files` lists are slim.
- Stale local browsing text is gone; regenerated pages reflect the merged snapshot.
- The backup directory still has the unpublished bundle, checksums, and preserved
  copies. Repeating apply is a no-op.

### Rollback

If apply refuses, the clone is unchanged and the backup is complete. If apply fails
after `stage` `reset` or `replaying`, rerun the same `--apply` command; do not create a
second backup directory. To restore the unpublished commit instead of continuing,
`git fetch --update-head-ok <backup>/unpublished.bundle` in the hidden clone and reset
to that commit only after confirming the bundle verifies. Leave `files/objects` in place
either way.

## Related

- [Contribute](index.md) — the section hub.
