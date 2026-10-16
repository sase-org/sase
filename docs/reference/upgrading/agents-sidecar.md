---
title: Agent hood synchronization upgrades
description: Upgrade notes for retired agent hood synchronization formats.
---

# Agent hood synchronization upgrades

This page records compatibility notes for earlier hood synchronization formats.

## Legacy v1 limitations

V1's top-level manifest and `agents/<machine-qualified-name>` files remain in place and
read-only. A v1 row has no trustworthy username owner, a shared machine token alone is
never proof of ownership, and v1 cannot reconstruct the complete transactional session
and relationship state guaranteed by v2. Current sync and status commands do not import
or retire v1 transport data. Already-imported local legacy history can be purged in full
(imports of any transport and any machine, plus historical import staging,
incoming-cache directories, and receipts) with `sase agent names purge-local-state`.

## Related

- [Upgrading](index.md) — the section hub.
