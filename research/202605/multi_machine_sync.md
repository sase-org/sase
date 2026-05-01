# Multi-Machine Sync for Sase: Research & Recommendation

## Goal

Let a user run sase on multiple machines (laptop, desktop, remote dev box) and have agents, ChangeSpecs,
chats, artifacts, and other state stay coherent across them — ideally without losing offline-first behavior
and without serializing all access through a server that has to be operated.

## What Lives in `~/.sase/`

Before designing sync, it helps to bucket the state by its update pattern, because no single sync mechanism
fits all of it.

| Bucket                | Examples                                                                                              | Update pattern                            | Conflict risk                | Sync needed?       |
| --------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------- | ---------------------------- | ------------------ |
| ChangeSpecs           | `projects/<p>/<p>.gp`, `<p>-archive.gp`                                                               | Line-oriented text, multiple writers/day  | High (concurrent edits)      | Yes — primary      |
| Chat transcripts      | `chats/<host>-<agent>-<ts>.md`                                                                        | Append-only during agent run, then frozen | Low (per-agent file)         | Yes — high volume  |
| Agent artifacts       | `projects/<p>/artifacts/<agent>/`, `axe/jacks/<id>/`                                                  | Write-mostly, finalized at agent exit     | Low (per-agent dir)          | Yes                |
| Bare workspace repos  | `repos/*.git`                                                                                         | git-fetch driven                          | None (already a remote)      | Indirectly         |
| Ephemeral runtime     | `axe/orchestrator.{lock,pid}`, `tui_pid`, `tui_idle_state`, `tui_last_activity`, `*.lock`, `pinned_*` | Continuously rewritten per-machine        | N/A                          | **Never**          |
| User history / prefs  | `prompt_history.json`, `command_history.json`, `query_history.json`, `file_reference_history.json`    | Frequent JSON rewrites                    | High (last-write-wins kills) | Yes — but tricky   |
| Coordination          | `agent_name_allocation.lock`, workspace claims                                                        | Cross-process critical sections           | Catastrophic if wrong        | Needs distributed  |
| Notifications / Hooks | `notifications/`, `comments/`, `hooks/`                                                               | Event streams                             | Low if file-per-event        | Yes                |
| Saved queries / state | `saved_queries.json`, `agent_tags.json`, `dismissed_agents.json`                                      | Occasional rewrites                       | Medium                       | Yes                |
| Workspace clones      | `../sase_<N>/` (next to repo, **not** in `~/.sase`)                                                   | Per-machine, ephemeral                    | N/A                          | Never              |

The volume problem is real: there are already ~17k chat files in `~/.sase/chats/`, and that grows monotonically.
The coordination problem is also real: `agent_name_allocation.lock` and workspace claims (see
`memory/short/glossary.md` "Retry chain" entry) assume a single machine sees all running agents.

## Prior Art

| System                                | Mechanism                              | Lessons for sase                                                                                                               |
| ------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **chezmoi**                           | Git-managed dotfiles with templates    | Already in the sase orbit. Great for static config, poor for high-churn state. Sase already uses it for dotfiles.              |
| **Syncthing**                         | P2P file sync, eventual consistency    | Zero-code, P2P, end-to-end encrypted in flight. Treats files as opaque blobs — concurrent JSON edits become `*.sync-conflict`. |
| **Atuin** (shell history)             | SQLite + dedicated sync server, E2EE   | Closest analog for sase's history JSONs. Proves the "small server + encrypted client diff sync" model works for dev tools.    |
| **Obsidian Sync / Obsidian Git**      | Either CRDT-ish proprietary or plain Git | Chats and ChangeSpecs are like an Obsidian vault. Git plugin works but conflicts on concurrent edits are common.              |
| **Logseq / Dendron / Foam**           | Markdown files + Git                   | Same trade-off: trivial setup, conflict-prone if multiple machines edit same file.                                             |
| **VS Code Settings Sync**             | GitHub-account-backed sync             | UX template: opt-in, scoped (which categories to sync), per-machine overrides.                                                 |
| **JetBrains Settings Sync**           | JetBrains cloud or Git repo            | Lets user pick the backend. Worth copying.                                                                                     |
| **Litestream**                        | SQLite WAL streamed to S3              | If sase ever consolidates state into SQLite (e.g. ChangeSpec index, history), this is the simplest replication story.          |
| **Dolt**                              | Git for relational data                | Overkill, but its merge semantics are the gold standard for structured state.                                                  |
| **Fossil SCM**                        | Single-binary VCS w/ built-in tickets, wiki, sync | Demonstrates that "code + tickets + chat" can share one sync substrate. Closest in spirit to ChangeSpec + chats. |
| **Automerge / Yjs**                   | CRDT libraries for collaborative state | Solves the JSON-conflict problem properly, at the cost of rewriting storage format.                                            |
| **rclone bisync**                     | Two-way sync to any cloud backend      | Cheap, scriptable, no daemon. Same conflict semantics as Syncthing.                                                            |
| **Tailscale Taildrop / Keybase FS**   | Auth'd P2P file transfer               | Useful as the *transport* layer; doesn't solve semantics.                                                                      |
| **Jupyter Hub / GitHub Codespaces**   | Centralized server, machines are dumb clients | Eliminates conflicts entirely. Operational cost is the killer for a single-user CLI tool.                              |

The honest summary: every prior art either **(a)** treats files as opaque and accepts conflict files, or
**(b)** runs a server and pays operational cost, or **(c)** rewrites storage to a CRDT/SQL schema. Sase
will need to pick one of those three, possibly per-bucket.

## Alternatives

### Alt 1 — Syncthing on `~/.sase/` with a curated `.stignore`

A long ignore list excludes `axe/orchestrator.*`, `tui_*`, `*.lock`, `*.pid`, the bare-repo dirs, and any
file written more than once per second. Everything else syncs P2P.

- **Pros:** Working in a weekend. P2P, no server. Already encrypted in transit. Append-only files (chats,
  artifacts) sync flawlessly. Survives offline.
- **Cons:** No semantic awareness. Concurrent ChangeSpec edits across two laptops will produce `.sync-conflict`
  files and the user has to merge by hand. JSON history files will lose entries. Doesn't help with agent-name
  or workspace coordination.

### Alt 2 — Git-backed sync (chezmoi-style for state)

Treat `~/.sase/` as a chezmoi-managed (or plain git) tree. `sase sync` = `git pull --rebase && git push`.
Per-machine ignore patterns via `.gitignore`. Reuse the chezmoi infra already documented in the long-term
memory.

- **Pros:** Free history, free `git blame` on ChangeSpecs, code-review-able. Integrates with the existing
  pattern from `research/202604/git_versioned_agent_memory.md`. Works offline, push when online.
- **Cons:** ~17k chat files makes the repo huge — needs LFS or shallow strategies. Bare repos under
  `repos/*.git` cannot live inside another git repo cleanly. Concurrent edits → text merge conflicts on
  `.gp` files (often resolvable, sometimes not). JSON history files merge poorly. Manual sync cadence
  unless wrapped in a daemon.

### Alt 3 — Cloud object storage (S3 / B2 / R2) via `rclone bisync`

`rclone bisync` between `~/.sase/` and a private bucket. Run periodically via cron / launchd / systemd timer.

- **Pros:** Cheap. Encrypted at rest. Works without P2P connectivity (good for laptop ↔ remote dev VM).
  Similar simplicity to Syncthing.
- **Cons:** Same conflict semantics — last writer wins, conflicts dumped to a sidecar file. Requires a
  cloud account. Latency is higher than Syncthing for small frequent changes.

### Alt 4 — Centralized sase backend (machines are thin clients)

Stand up a sase server: ChangeSpecs in Postgres, chats in object storage with hostname-prefixed keys,
artifacts as blobs, `agent_name_allocation` and workspace claims as DB rows with leases. CLI talks to the
server; local cache is a read-through.

- **Pros:** Conflicts and coordination disappear. Same backend powers the web client research already on
  file (`research/202604/sase_web_client_research.md`). Multi-machine becomes a first-class feature, not
  a hack.
- **Cons:** Largest project on this list. Sase becomes online-or-degraded by default; offline support
  needs a real local cache layer. Operational burden — auth, backups, migrations, hosting. Probably a
  6–12 month lift before it's better than the status quo.

### Alt 5 — Per-domain hybrid (different mechanism per bucket)

Pick the right tool per bucket using the table at the top:

- **ChangeSpecs** → per-project Git remote. `<proj>.gp` and `<proj>-archive.gp` live in a small repo per
  project (or a shared "sase-state" repo). Reuses the design from the git-versioned memory research.
  Merge conflicts in `.gp` are usually trivial because edits are line-scoped.
- **Bare repos under `repos/`** → already have upstream remotes; `git fetch` covers them. Don't sync
  `.git` dirs, just re-fetch on each machine.
- **Chats / artifacts** → object storage (S3/B2/R2) or Syncthing. Filenames are already hostname-and-
  timestamp-prefixed (`bbugyi200-ace_run-260218_174240.md`), so chats from different machines never
  collide. Append-only after the agent ends. Lifecycle policy can prune > N months.
- **History/prefs JSON** → Atuin-style: a small SQLite per host with a sync server, OR keep them per-
  machine and explicitly do **not** sync them. (User preferences for prompt history are arguably per-
  machine anyway.)
- **Ephemeral state** → never syncs.
- **Coordination (agent name leases, workspace claims)** → small networked coordinator. Could be a single
  Postgres advisory-lock service, a Redis with leases, or piggy-back on the centralized server in Alt 4
  if/when it exists. Until it exists, document "one machine drives at a time" and have `sase` refuse to
  spawn agents on Machine B while Machine A holds an active lease file in the synced directory.

- **Pros:** Each bucket gets a sync model that fits. Most of it is composed from boring infrastructure
  (git, S3, Syncthing) rather than new code. Migration can be staged.
- **Cons:** N moving parts to document and operate. The coordination piece still requires a server in
  the long run.

### Alt 6 — Local-first CRDT rewrite (Automerge / Yjs)

Move ChangeSpecs and history into Automerge documents; sync via any byte transport (Syncthing, S3,
custom).

- **Pros:** Conflict-free by construction. Excellent fit for the "edit on plane, edit on phone, merge
  later" workflow.
- **Cons:** Major storage-format migration. ChangeSpecs lose their human-greppable plain-text property
  (or you keep both formats and double-write, which is its own footgun). Significant new dependency.
  Probably wrong tool unless multi-user collaboration becomes a goal.

## Comparison

| Criterion              | Syncthing | Git/chezmoi | rclone | Server   | Hybrid  | CRDT     |
| ---------------------- | --------- | ----------- | ------ | -------- | ------- | -------- |
| Offline-first          | Yes       | Yes         | Yes    | Degraded | Yes     | Yes      |
| Time-to-first-working  | Days      | Week        | Days   | Months   | Weeks   | Months   |
| Conflict handling      | Files     | Text merge  | Files  | None     | Mixed   | Auto     |
| Solves coordination?   | No        | No          | No     | Yes      | Partial | No       |
| Operates a server?     | No        | No          | No     | Yes      | Eventually | No    |
| Handles 17k+ chats     | Good      | Needs LFS   | Good   | Good     | Good    | Awkward  |
| ChangeSpec history     | None      | Free        | None   | Yes      | Free    | Yes      |
| Implementation cost    | Low       | Low–Med     | Low    | High     | Med     | High     |
| Ongoing user friction  | Low       | Low         | Low    | None     | Low     | Low      |

## Recommendation

**Adopt Alt 5 (per-domain hybrid), staged in three phases.** It composes existing infrastructure rather
than building a server, gives each bucket a fitting sync model, and leaves the door open to graduate to
Alt 4 (centralized backend) once the web-client work lands.

### Phase 1 — Cover 90% of the data with Syncthing (1–2 weeks)

1. Ship a curated `~/.sase/.stignore` covering `axe/orchestrator.*`, `tui_*`, `*.lock`, `*.pid`,
   `repos/*.git/`, `*.sync-conflict`, `command_history.json`, `prompt_history.json` (and any other
   per-machine JSON).
2. Add a `sase sync doctor` command that lints the user's Syncthing folder config against a known-good
   ignore set and warns if a forbidden file is being shared.
3. Document the model: "chats and artifacts sync; per-machine state does not; only run agents on one
   machine at a time until Phase 3."

This alone covers chats, artifacts, project files, notifications, and most preferences — by file count,
the vast majority of what users want.

### Phase 2 — Promote ChangeSpecs to per-project Git remotes (2–4 weeks)

This piggy-backs on the design already worked out in `research/202604/git_versioned_agent_memory.md`:

- `~/.sase/projects/<proj>/` becomes a git working tree with `.gp` / `<proj>-archive.gp` / `memory/` in
  it.
- `sase sync` runs `git pull --rebase && git push` on every project repo.
- Merge conflicts in `.gp` files use a custom git merge driver that understands ChangeSpec entry
  boundaries, so two agents touching different ChangeSpecs auto-merge cleanly. (The format is
  entry-delimited; this is achievable.)
- ChangeSpecs leave the Syncthing folder once they live in git, eliminating the most conflict-prone
  bucket from Phase 1.

### Phase 3 — Add a tiny coordinator for cross-machine safety (when needed)

The minimum viable coordinator is a single endpoint (or a row in a hosted Postgres) that issues:

- agent-name leases (TTL'd, renewed by heartbeat),
- workspace claims (the same primitive used by spawn-on-retry, but now machine-aware).

This is one small service, probably a few hundred lines, and it removes the "only one machine at a time"
caveat. It is also the natural seed of the Alt 4 server should sase ever go that direction.

### What this explicitly does *not* do

- Does not rewrite ChangeSpec or history into a CRDT (Alt 6) — premature.
- Does not stand up a full backend (Alt 4) — wait for the web-client work to demand it.
- Does not try to sync `~/.sase/repos/*.git` directly — those are clones with upstreams already.
- Does not try to merge `prompt_history.json` across machines — it's arguably per-machine anyway, and
  doing it right needs Atuin-style infrastructure that isn't worth the code.

### Risks to watch

- **Workspace claim correctness across machines.** Until Phase 3, two machines can both think they own
  the same agent name. Mitigation: ship a `sase sync status` that surfaces lease conflicts loudly, and
  default new installs to "passive mode" on secondary machines.
- **Chat volume in Syncthing.** 17k files today, growing. Verify Syncthing's scanner cost and consider
  partitioning chats by month-directory if scan time becomes a problem.
- **`.gp` merge driver edge cases.** Concurrent edits to the *same* ChangeSpec (rare but possible) need a
  three-way merge or human resolution. Ship the merge driver with conservative fallback to manual.
