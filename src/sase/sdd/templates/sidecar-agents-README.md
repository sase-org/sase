# SASE Agents Sidecar

This repository stores deterministic, owner-sharded snapshots of complete project-scoped SASE agent hoods.

## Privacy and publication

One publication includes every locally owned active, waiting, terminal, failed, and dismissed run in the committing
agent's top-level hood. It can publish active prompts before a transcript exists and refresh the same stable run later
with terminal state, commits, or chat. The repository's configured visibility controls who can access that data. Set
the `agents` sidecar visibility to `private` before creation to restrict access, or set `disabled: true` to opt out.

![Project-scoped agent hoods pass through explicit privacy consent into an owner-sharded agents sidecar, where deterministic sync publishes prompts, chats, commits, states, and browsable owner, machine, hood, family, and agent pages.](assets/agents-directory-map.png)

## Snapshot layout

- `schema.json` identifies the strict v2 format.
- `users/<username>/machines/<machine>/manifest.json` is one owner's authority file.
- `users/<username>/machines/<machine>/hoods/<hood>/snapshot.json` captures a complete hood.
- `agents/<global-name>/` contains allowlisted metadata, state, commits, prompt, and optional chat.
- `families/<global-family>.md` and the generated `README.md` pages provide deterministic browsing.
- `prompts/<YYYYMM>/<name>.md` stores both forms of a canonical committed run prompt: the XPrompt prompt keeps its
  unexpanded `#...` references in the document body, while the final rendered prompt sent to the model appears in a
  collapsed verbatim section. Each prompt links back to its plan when it has one, links to the published agent page,
  and rewrites captured `@...` artifact references and resolvable `#...` xprompt references into clickable inline
  links. Unresolvable xprompt references remain exactly as typed.
- `prompts/<YYYYMM>/README.md` is the generated month index for prompt archive browsing.
- `artifacts/<YYYYMM>/<sha12>-<basename>` stores copied prompt-linked artifact bytes. The twelve-character prefix is
  the start of the file's SHA-256 digest; VCS-backed prompt links point to hosted source blobs instead of duplicating
  bytes here.

Legacy top-level `manifest.json` and v1 agent bundles remain readable but are not rewritten. Run `sase agent sync` to
reconcile eligible local hoods with the configured sidecar repository, or `sase agent prompts validate` to audit the
prompt and artifact archive.
