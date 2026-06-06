# Running SASE Agents On Remote Machines Via An Always-Online Broker

Date: 2026-06-06
Status: research / design memo with recommendation

## Question

The user wants to run SASE agents on remote machines by using a server they already own that is always online as a
remote endpoint "that other machines can send and pull work to and from." What is the best way to implement this?

This is a *pull-oriented broker* framing: one stable, always-reachable server in the middle; several machines around it
that both submit work and execute work. That framing is subtly but importantly different from the prior remote-execution
research on file, so this memo builds on those notes rather than repeating them.

## Relationship To Prior Research

Four existing notes already cover adjacent ground. Read them alongside this memo; this note does not duplicate their
detail.

| Prior note | What it covers | What it leaves open (this memo's job) |
| --- | --- | --- |
| `202606/apollo_remote_agents_workspace_topology.md` | A **push / direct-dispatch** model: a controller picks an execution host and starts the runner there. Stable project identity, host-qualified leases, staged rollout. | Assumes the controller can *reach* each execution host. Does not address a central always-online rendezvous, NAT'd workers, or a durable queue machines pull from. |
| `202605/multi_machine_sync.md` | Keeping `~/.sase` **state** coherent across machines (Syncthing/git/hybrid). Buckets state by churn; flags coordination (agent-name leases, workspace claims) as the hard part. | Sync ≠ execution. It explicitly defers the "tiny coordinator" that issues leases — which a broker can *be*. |
| `202605/same_named_github_repos.md` | Owner-qualified canonical project identity for GitHub repos. | The identity prerequisite for *any* cross-host execution. |
| `202604/sase_web_client_research.md` | A local-first `sase-server` (axum + REST/OpenAPI + SSE) for a web UI. | Loopback-only by design; not a remote work queue, but the same server backbone. |

The single most important code finding for this question is not in any of those notes:

> **SASE already ships ~70% of the transport.** The **mobile gateway** (`../sase-core/crates/sase_gateway`) is a Rust
> HTTP server with pairing/token auth, an audit log, an SSE event stream, a committed API-contract snapshot, and fixed
> bridge commands that **list / launch / kill / retry agents** (`sase.integrations.mobile_agents`) plus workflow
> helpers and notifications. Its documented remote-access path is **Tailscale Serve**
> (`docs/mobile_gateway.md`, `docs/mobile_mvp_runbook.md`).

That changes the recommendation: the cheapest first version of "remote agents" is not new infrastructure, it is pointing
existing infrastructure at an always-online host on a tailnet.

## Current Topology: SASE Is Local-Only To Execute

The launch/run pipeline is entirely local (traced from `src/sase`):

- **Launch** builds an `AgentLaunchRequestWire` (`src/sase/core/agent_launch_wire.py:16`) carrying *local* paths —
  `project_file`, `workspace_dir`, `workspace_num`, prompt text. `prepare_agent_launch()`
  (`src/sase/core/agent_launch_facade.py:28`) writes a temp prompt file and an argv of
  `python -m sase.axe.run_agent_runner …`. `spawn_agent_subprocess()` (`src/sase/agent/launch_spawn.py:97`) spawns a
  **detached** local process via the Rust-backed `spawn_prepared_agent_process()` and gets back a **local PID**.
- **Runner** (`src/sase/axe/run_agent_runner.py`) reads the local prompt file, `os.chdir`s into the local workspace,
  shells out to the provider CLI (`claude`, `codex`, …), and writes artifacts under
  `~/.sase/projects/<project>/artifacts/ace-run/<ts>/` (`agent_meta.json`, `workflow_state.json`, `running.json`,
  `done.json`, logs).
- **Claims** live in the ProjectSpec `RUNNING` field as `#<num> | <pid> | <workflow> | <cl> | <ts>`
  (`src/sase/running_field/_model.py:33`). Liveness is `os.kill(pid, 0)` + `/proc/<pid>/cmdline` checks
  (`src/sase/ace/hooks/processes.py:36`). Kill is `os.killpg(pid, SIGTERM)`. **PID is assumed globally unique.**
- **Daemon** (`axe`, `src/sase/axe/process.py`) is a *single-machine* orchestrator of interval "lumberjacks"
  (hooks 5s, waits 10s, checks 5min …). It is not a network service.
- **LLM/VCS providers** always shell out to local CLIs (`src/sase/llm_provider/_subprocess_*.py`). There is no remote
  LLM transport in SASE; the local CLI talks to the model API.

Hard local assumptions to break for true remote execution: PID identity, `/proc` liveness, signal-based kill, `chdir`
into a local checkout, local temp prompt file, and local artifact paths.

## The Decisive Choice: What Role Does The Always-Online Server Play?

"Run agents on remote machines via an always-online server" collapses into one design decision. Pick the server's role;
everything else follows.

### Role A — The always-online server is the *execution host*

Other machines are thin **remote controls**. They submit a prompt and read results; the agent actually runs on the
always-online box. The phone-gateway model, generalized to any client.

- **Maps almost 1:1 onto shipped code.** The gateway already launches/lists/kills/retries agents and streams SSE.
- No project-identity work needed: the one host materializes everything locally, exactly as today.
- No cross-host PID/lease/claim problem: claims stay on one machine.
- Limitation: all work runs on *one* box. No fan-out across machines. The box must hold every project's checkout and
  credentials.

### Role B — The always-online server is a *broker / coordinator*

It holds a durable **job queue** and hands out leases. The *other* machines are **workers** that pull jobs, run them
locally, and stream results back. This is the user's literal "send and pull work to and from" model.

- Fan-out across many workers; the powerful always-online box can itself be one worker.
- **NAT-friendly:** workers and submitters only ever connect *outbound* to the broker, so laptops/home boxes behind a
  router need no port-forwarding or public address — only the broker needs a stable address.
- Cost: this is real new code — a durable queue, a `sase worker` poll loop, result/artifact flow-back, and the
  cross-host coordination (`PID` → host-qualified handle, leases with fencing) that `multi_machine_sync.md` and
  `apollo_remote_agents_workspace_topology.md` both flagged as the hard part. It **requires** provider-normalized
  project identity first (`same_named_github_repos.md`), because a worker on a different machine must independently
  materialize "the same repo."

### Push vs. pull, and why the user's framing points to pull

There are three ways to get a job onto a remote machine:

| Model | How work reaches the worker | Reachability requirement | Fits "always-online + other machines"? |
| --- | --- | --- | --- |
| **SSH / direct dispatch** (simplest push) | Controller `ssh`es in and starts the runner | Controller must reach **every** worker (address + port + key) | Poorly — every worker must be a reachable server |
| **Apollo provider** (structured push) | Controller RPCs a chosen host to start the runner | Same: controller → host reachability | Same limitation, just nicer |
| **Broker / queue** (pull) | Worker polls the broker and pulls the next job | Only the **broker** needs a stable address; workers dial out | **Yes** — this is the user's description |

The user explicitly has *one* always-online machine and wants *other* machines (plural, likely including NAT'd
laptops) to participate. That constraint is exactly what pull-based brokering is for: one rendezvous point, everyone
else connects outbound. Push models (SSH, Apollo) are a worse fit here precisely because they invert the reachability
requirement.

## Cross-Cutting Surfaces (apply to Role B; Role A mostly sidesteps them)

These are the surfaces every remote-execution design must answer. Role A avoids most of them because execution and
state stay on one host; Role B must handle each.

1. **Network substrate.** Do **not** expose the broker on the public internet. Put the always-online server and all
   machines on a **Tailscale / WireGuard tailnet** (or equivalent). This is already SASE's documented remote-access
   path for the gateway (`docs/mobile_mvp_runbook.md`, Tailscale Serve), and it solves NAT traversal, stable
   addressing, transport encryption, and device identity in one move. Keep the broker bound to the tailnet interface;
   keep a bearer/pairing token on top (defense in depth, matching the gateway's existing pairing/token store).

2. **Project identity (hard prerequisite for Role B).** A worker must turn a job into the *same* repository the
   submitter meant. Land the owner-qualified canonical id from `same_named_github_repos.md` /
   `apollo_remote_agents_workspace_topology.md` Stage 0: `canonical_project_id = github:owner/repo`, display name
   separate, aliases as the ergonomic front door. Without it, the same repo becomes different projects on different
   hosts.

3. **Source materialization.** Sync code through **real VCS remotes**, GitHub-first — a worker clones/fetches
   `owner/repo` itself. Bare-git projects need a declared network remote or they fail before launch; `#cd` path
   workspaces are local-only. (Same conclusion as the Apollo memo.)

4. **Credentials.** Assume **self-credentialed workers** for the first versions: SASE installed, provider CLIs present
   and authed (`gh`, `claude`, `codex`), repo remote reachable. The broker forwards *jobs*, not secrets. Secret
   forwarding is a later, audited, narrow capability — never the default.

5. **Result / artifact flow-back.** Mirror only small, user-facing artifacts to the submitter/broker: `agent_meta.json`,
   `workflow_state.json`, `running.json`, `done.json`, plan/question markers, explicit user artifacts. Stream live log
   output (SSE — the gateway already does this). Leave heavy diagnostics (`axe/logs`, which `multi_machine_sync.md`
   measured at ~64 GiB) host-local with fetch-on-demand. This is the Apollo memo's "mirror metadata, fetch blobs"
   stance, and it lets the existing TUI/ace artifact scanner keep working against mirrored files.

6. **Coordination / leases.** The broker is the natural home for the "tiny coordinator" `multi_machine_sync.md`
   Phase 3 deferred: TTL'd agent-name leases and workspace claims keyed by `(host_id, canonical_project_id,
   workspace_num)`, renewed by heartbeat, with an epoch/fencing token. The local `RUNNING`-field PID model
   (`src/sase/running_field/_model.py`) must grow a host-qualified handle (`run_id`, `host_id`, `remote_pid`,
   `lease_token`, `last_heartbeat_at`) instead of treating PID as globally unique. Per the Rust-core boundary, model
   this handle in `../sase-core` once stable.

## Implementation Options For The Broker (Role B transport)

If/when Role B is built, the queue itself can be self-built or off-the-shelf.

| Option | What it is | Pros | Cons | Verdict |
| --- | --- | --- | --- | --- |
| **Build into `sase-core`** (extend/sibling `sase_gateway`): axum HTTP+SSE + a durable **SQLite-backed** job table | One binary the user runs on their box: `sase serve` / `sase broker` | Reuses pairing/token auth, audit log, SSE, contract-snapshot tooling already in `sase_gateway`; no new external dependency; honors the Rust-core boundary; web-client research already endorses this exact stack | You write the queue + lease logic (a few hundred lines); durability/visibility-timeout semantics are yours to get right | **Recommended** — best cohesion with the codebase |
| **NATS JetStream** | Tiny single-binary message broker with durable work queues, request/reply, consumer groups | Pull semantics + durability + heartbeats for free; clients dial out (NAT-friendly); TLS + token/nkey auth; well-suited to exactly this | New runtime dependency to operate; SASE still needs a worker shim and result flow-back | Strong pragmatic alternative if you'd rather not write queue/lease code |
| **Redis (lists/streams) or cloud queue (SQS)** | Generic queue primitives | Familiar; managed option (SQS) needs no server | Redis needs hardening for durable job semantics; SQS is a cloud dependency and weaker for live streaming | Fallback, not preferred for a single-user self-hosted box |
| **Plain SSH fan-out** | No broker; dispatch over SSH | Zero new services | Push model — fails the NAT/always-online framing; no queue, no leases | Only as a stopgap (see Phase 0) |

For a single user who already owns an always-online box, the choice is between **build-into-core** (maximum cohesion,
reuses the gateway) and **NATS JetStream** (least code, proven semantics). Lead with build-into-core; fall back to NATS
if queue/coordination correctness becomes a tar pit.

## Recommendation

Adopt a **pull-based broker on a private tailnet, reached first through the existing mobile gateway and graduated to a
real queue only when multi-worker fan-out is actually needed.** Stage it so value lands in days, not months.

### Phase 0 — Network substrate (hours)

Put the always-online server and every participating machine on a **Tailscale/WireGuard tailnet**. This is the
foundation for everything below and is already SASE's documented gateway remote-access path. Nothing else here should
ever bind to a public address.

### Phase 1 — Role A: remote agents *now*, almost no new code (days)

Run the shipped **`sase_gateway` on the always-online server**, bound to the tailnet interface (`allow_non_loopback`,
guarded behind the tailnet + pairing token). Execution happens on that server; laptops/phones submit prompts and watch
SSE results as gateway clients via `sase.integrations.mobile_agents` (list/launch/kill/retry).

This delivers "run SASE agents on a remote always-online machine, controlled from anywhere" with essentially
configuration + a small amount of CLI glue. It is the 80% outcome. Validate it before building the broker.

Gaps to close as small follow-ups: the gateway client surface is phone-shaped; a thin `sase remote …` CLI client (or
the planned web client pointed at the tailnet host) makes laptop-to-server submission ergonomic.

### Phase 2 — Identity hardening (weeks, parallelizable)

Land provider-normalized canonical project identity (GitHub-first), per `same_named_github_repos.md` and Apollo Stage 0.
This is the gate before any *worker that is not the submitter* can materialize the right repo. It is independently
useful (it fixes duplicate-project bugs today) and is the prerequisite for Phase 3.

### Phase 3 — Role B: the broker/queue the user described (the larger build)

Turn the always-online server into a true broker:

1. Add a durable job queue to `sase-core` (recommended) alongside `sase_gateway`, or stand up NATS JetStream.
2. Submitters `POST` a job (canonical project id + workflow + prompt + ref); the broker enqueues it durably.
3. A `sase worker` process on each machine dials the broker outbound, **pulls** the next job, materializes the repo
   from its VCS remote, and launches it through the *existing local launch path* — reusing the same bridge/launch
   commands the gateway already calls.
4. Workers stream live logs (SSE) and mirror small status/artifacts back; heavy diagnostics stay host-local.
5. The broker issues TTL'd, heartbeat-renewed **leases** for agent names and workspace claims with fencing — finally
   delivering the coordinator `multi_machine_sync.md` deferred. Extend the `RUNNING`-handle to be host-qualified.

Start with one self-credentialed worker (which may be the always-online box itself), GitHub projects only, then add
workers. Keep "one broker owns claims" as an explicit invariant until fencing is proven.

### Why this order

- **Fastest value, least risk:** Phase 1 reuses a shipped, tested, security-reviewed server instead of building one.
- **Honors the constraints:** the tailnet + pull broker is exactly right for "one always-online box, other machines
  (some NAT'd) send and pull work."
- **Doesn't re-litigate solved questions:** identity, artifact-mirroring, and lease coordination already have agreed
  designs in prior memos; this plan sequences them rather than reinventing them.
- **Respects the Rust-core boundary:** queue, leases, and the host-qualified handle belong in `sase-core` next to the
  gateway; Python stays the launch/runner glue.

The core invariant remains the Apollo memo's: **project identity is "what repo is this"; a workspace is "where a host
materialized it."** The broker brokers the second without minting new identities for the first.

## Risks And Open Questions

- **Worker liveness across machines.** PID/`/proc` checks are local-only. Phase 3 must replace them with broker
  heartbeats + fencing, or two machines will both believe they own an agent name.
- **Credential sprawl.** Self-credentialed workers are fine for a personal fleet; ephemeral cloud workers would need a
  real secret-distribution story that this plan deliberately defers.
- **Result-state coherence.** Mirroring metadata keeps the local artifact scanner working, but a host-aware scanner is
  a larger later change; until then, treat the submitter's view as a mirror, not the source of truth.
- **Don't double-build a server.** The web-client research (`sase_web_client_research.md`) and this memo both want a
  `sase-core` HTTP server. They should converge on **one** server backbone (loopback web UI + tailnet broker as bind
  modes of the same crate), not two.
- **Bare-git / `#cd` projects** have no network remote and cannot be materialized remotely without an explicit publish
  step; they must fail before launch with a clear reason.
- **Build vs. NATS** for the queue is the main open implementation decision; resolve it at the start of Phase 3 based on
  appetite for writing durable-queue/lease code.

## Sources

Local:

- `src/sase/integrations/mobile_gateway.py` (gateway lifecycle, `allow_non_loopback`, bind guard)
- `docs/mobile_gateway.md`, `docs/mobile_mvp_runbook.md` (gateway architecture, Tailscale Serve remote access)
- `src/sase/core/agent_launch_wire.py`, `agent_launch_facade.py`, `src/sase/agent/launch_spawn.py`,
  `src/sase/agent/launch_executor_workspace.py` (launch path)
- `src/sase/axe/run_agent_runner*.py` (runner phases, artifact writes)
- `src/sase/running_field/_model.py`, `_operations.py` (claims, PID model)
- `src/sase/ace/hooks/processes.py` (local liveness/kill)
- `src/sase/axe/process.py` (single-machine daemon)
- `src/sase/llm_provider/_subprocess_*.py`, `src/sase/workspace_provider/_hookspec.py` (provider plugin pattern)
- `src/sase/config/core.py` (layered config; where a `remote`/`broker` section would live)
- `sdd/research/202606/apollo_remote_agents_workspace_topology.md`
- `sdd/research/202605/multi_machine_sync.md`
- `sdd/research/202605/same_named_github_repos.md`
- `sdd/research/202604/sase_web_client_research.md`
- `memory/short/rust_core_backend_boundary.md`

External:

- Tailscale Serve / tailnet remote access: <https://tailscale.com/kb/1242/tailscale-serve>
- NATS JetStream work queues: <https://docs.nats.io/nats-concepts/jetstream>
- WireGuard: <https://www.wireguard.com/>
