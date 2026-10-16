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
available, SASE records an outbox request for the exact hood and immediately drains it
under the bounded agents lock, so the commit does not return until the hood is published
and pushed (or the request is confirmed queued for retry). A publication that cannot
even be queued fails the commit with a `sase stitch create --resume` hint; a request
that survives the immediate drain — because of a transient, hood-specific, or
repository-wide failure — prints a warning naming the recovery command and is retried by
a later commit's drain or by an explicit `sase agent sync`. See
[runtime provenance and publication](commit-workflow-orchestrator.md#cli-inputs-and-internal-payload).

Published runs that are temporarily missing from local inventory are retained. New
terminal state, commits, prompt data, and chat refresh the same stable run; absence does
not create an implicit deletion or tombstone. Identical inputs produce byte-identical
files and a no-op publication.

After each pull/rebase, SASE rebuilds root, user, machine, hood, session, and agent
Markdown from every validated owner manifest. Index and neighbor pages link a _specific
run_, so their session member links use stable `member-<role>` anchors; solo links
target the corresponding agent README. Commit footers are the other case: they identify
a sase agent rather than a run, so they link the session page with no member anchor (see
[runtime provenance](commit-workflow-orchestrator.md#cli-inputs-and-internal-payload)).
Because owners mutate disjoint authority files, a bounded non-fast-forward retry can
pull a competing owner, recompute the shared views, and converge without overwriting
either snapshot.

## Related

- [Contribute](index.md) — the section hub.
