# SASE Agents Sidecar

This repository stores deterministic, owner-sharded snapshots of complete project-scoped SASE agent hoods.

## Privacy and publication

One publication includes every locally owned active, waiting, terminal, failed, and dismissed run in the committing
agent's top-level hood. It can publish active prompts before a transcript exists and refresh the same stable run later
with terminal state, commits, or chat. The repository's configured visibility controls who can access that data. Set
the `agents` sidecar visibility to `private` before creation to restrict access, or set `disabled: true` to opt out.

## Snapshot layout

- `schema.json` identifies the strict v2 format.
- `users/<username>/machines/<machine>/manifest.json` is one owner's authority file.
- `users/<username>/machines/<machine>/hoods/<hood>/snapshot.json` captures a complete hood.
- `agents/<global-name>/` contains allowlisted metadata, state, commits, prompt, and optional chat.
- `families/<global-family>.md` and the generated `README.md` pages provide deterministic browsing.

Legacy top-level `manifest.json` and v1 agent bundles remain readable but are not rewritten. Run `sase agent sync` to
reconcile eligible local hoods with the configured sidecar repository.
