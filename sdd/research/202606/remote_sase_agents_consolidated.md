---
create_time: 2026-06-06
updated_time: 2026-06-06
status: research
---

# Remote SASE Agents Via An Always-Online Endpoint

## Question

How should SASE support running agents on remote machines when the user already
has an always-online server that other machines can send work to and pull work
from?

This consolidates the two June 2026 remote-agent research notes:

- `sdd/research/202606/remote_agent_endpoint_queue_architecture.md`
- `sdd/research/202606/remote_agent_work_broker.md`

It also builds on the existing Apollo, multi-machine sync, same-named GitHub
repo, and web-client research.

## Consolidated Answer

Use a staged design with two distinct roles:

1. **Execution host first.** Put the always-online server on a private tailnet
   and run the existing SASE mobile gateway there. Other machines submit and
   monitor work as clients; agents execute on the server. This gives remote
   agents quickly with little new code.
2. **Broker later.** When work needs to fan out across several machines, turn
   the always-online server into a pull-based broker. Workers on each machine
   connect outbound, claim jobs, run the whole SASE runner locally, heartbeat
   their lease, stream events/logs, and mirror small artifacts back.

The user's "send and pull work" framing points to the broker model, but the
existing gateway should be used first because it already covers most of the
remote-control transport.

## Verified Current State

SASE execution is local today:

- `src/sase/core/agent_launch_wire.py` carries local `project_file`,
  `workspace_dir`, `workspace_num`, and `pid` fields.
- `src/sase/agent/launch_spawn.py` builds a local runner invocation and calls
  Rust-backed detached process spawning.
- `src/sase/axe/run_agent_runner.py` reads a local prompt file, `chdir`s into a
  local workspace, invokes local LLM/VCS/provider CLIs, and writes local
  artifacts.
- `src/sase/running_field/_model.py` stores `RUNNING` claims as
  `#N | PID | WORKFLOW | CL_NAME | TIMESTAMP`.
- `src/sase/ace/hooks/processes.py` uses local process APIs such as
  `os.kill`, `/proc/<pid>`, and process groups for liveness and kill.

Those assumptions make file sync or path remoting insufficient. Remote support
needs host-qualified run identity, leases, heartbeats, and artifact flow-back.

SASE also already has a strong remote API precedent:

- `docs/mobile_gateway.md` describes a Rust HTTP gateway with pairing/token
  auth, an audit log, SSE events, and fixed bridge commands.
- The bridge exposes product-shaped operations such as agent list, launch, kill,
  and retry. It does not expose arbitrary shell, cwd, env, argv, or host paths.
- `docs/mobile_mvp_runbook.md` already recommends Tailscale Serve for private
  remote access while keeping the gateway bound to loopback.

That gateway is the right starting point for the always-online server.

## Role A: Always-Online Server As Execution Host

In Role A, laptops, phones, or other clients only submit prompts and observe
state. The agent runs on the always-online server.

Benefits:

- maps closely to the existing gateway;
- keeps ProjectSpec claims, PIDs, workspaces, provider CLIs, credentials, and
  artifacts on one machine;
- requires no distributed scheduler or cross-host project identity to get
  started;
- is enough for "run SASE agents on my server from anywhere."

Limitations:

- all execution capacity is on the server;
- the server needs the relevant checkouts and credentials;
- it does not let a laptop or workstation pull jobs and execute them locally.

This should be the first implementation target.

## Role B: Always-Online Server As Pull Broker

In Role B, the server coordinates work and durable state, while workers execute
on their own machines.

The broker owns:

- submitted runs and their state;
- worker inventory and capabilities;
- leases, lease epochs, and heartbeat deadlines;
- cancellation requests;
- ordered run events;
- artifact manifests and small mirrored artifacts;
- audit records.

Each worker:

- connects outbound to the broker over HTTPS;
- registers `host_id`, SASE version, labels, capabilities, OS/arch, workspace
  root, provider availability, and concurrency;
- claims compatible work using a server-issued lease;
- materializes source code locally, preferably from VCS remotes;
- executes the whole SASE runner locally;
- streams events/log chunks and mirrors small artifacts;
- turns broker cancellation into local process termination.

The server may also run a worker, but server and worker are separate roles.

## Why Pull Beats Push Here

The alternatives differ mainly in reachability:

| Model | How work reaches execution host | Reachability requirement | Fit |
| --- | --- | --- | --- |
| SSH/direct dispatch | Controller pushes a command to a host | Controller must reach every host | Useful for debugging, poor default |
| Apollo-style push | Controller RPCs a selected execution host | Controller must reach every host | Good contract, wrong network shape |
| Broker/pull | Worker polls or holds a stream to the server | Only broker needs a stable address | Best fit |

Self-hosted runner systems use the same operational shape. Buildkite agents
poll the Buildkite API over HTTPS, need no incoming firewall access, then stream
output and final status back. GitHub self-hosted runners connect to GitHub to
receive job assignments and require outbound HTTPS. Temporal task queues persist
tasks when workers go down and are polled by workers.

## Critical Design Requirements For Role B

**Private network.** Put the server and workers on Tailscale or WireGuard. Use
Tailscale Serve for private HTTP exposure and avoid public Funnel or public
tunnels by default. Keep bearer or worker tokens on top of tailnet identity.

**Project identity.** A worker must know which repository to materialize.
GitHub-first canonical identity, such as `github:owner/repo`, is a prerequisite.
The May same-named repo research and June Apollo research already point in this
direction. Local `#cd` projects are local-only unless explicit path mappings or
shared mounts are configured. Bare-git projects need a declared network remote.

**Source movement.** Move source through real VCS remotes, not through the SASE
broker. The broker sends a materialization plan; the worker clones/fetches.

**Credentials.** Start with self-credentialed workers. Each worker has SASE,
provider CLIs, `git`/`gh`, Codex/Claude auth, and repository access installed
locally. The broker forwards jobs, not secrets.

**Execution unit.** Run a SASE-owned command on the worker, not arbitrary shell.
For the first broker version, prefer a foreground child supervised by
`sase worker` over today's detached PID model; that makes cancellation, live
logs, and terminal state easier to report. Internally, reuse the existing runner
path with remote metadata injected.

**Leases and fencing.** Replace PID-only identity with `run_id`, `host_id`,
`remote_pid`, `lease_epoch`, and `lease_expires_at`. Accept worker events only
when `(run_id, host_id, lease_epoch)` matches the current lease. A stale lease
means the server no longer trusts that worker to mutate the run; it does not
prove the local process is dead.

**Artifacts.** Mirror small status artifacts eagerly: `agent_meta.json`,
`running.json`, `done.json`, `workflow_state.json`, prompt snapshots,
plan/question/HITL markers, transcript summaries, bounded logs, and explicit
user artifacts. Keep large provider logs, `axe/logs`, raw workspaces, and large
blobs host-local or fetch-on-demand.

**Audit and safety.** Audit submit, claim, heartbeat, cancel, artifact upload,
and terminal outcomes. Never accept controller-supplied shell, cwd, env, argv,
or host paths.

## Broker Shape

Minimum server model:

```text
workers(host_id, display_name, version, labels, capabilities,
        max_concurrency, last_heartbeat_at, state)

runs(run_id, canonical_project_id, workflow_name, prompt_snapshot,
     materialization_plan, desired_labels, status, priority,
     assigned_host_id, lease_epoch, lease_expires_at,
     cancel_requested_at, terminal_outcome)

run_events(run_id, seq, host_id, lease_epoch, kind, payload, created_at)

artifacts(run_id, host_id, kind, name, size_bytes, content_hash,
          storage_uri, mirrored, created_at)
```

Minimum API:

- controllers: submit run, get run, stream/read events, cancel run, fetch
  artifact;
- workers: register, heartbeat, claim work, renew run lease, append events/logs,
  upload artifact manifests/blobs, complete run.

Use long polling or SSE first. WebSockets can come later if log latency or
bidirectional worker control needs it.

## Storage Decision

The two prior notes differed on SQLite versus PostgreSQL. The best resolution is
stage-dependent:

- **Phase 1 gateway:** no new queue store.
- **Single-process broker MVP:** SQLite is acceptable and keeps the endpoint
  single-binary if every worker goes through one server process and no worker
  writes the database directly.
- **Larger durable broker:** PostgreSQL is the better target once there are
  many workers, retention queries, or a desire for stronger operational
  visibility. PostgreSQL `FOR UPDATE SKIP LOCKED` is explicitly useful for
  queue-like tables with multiple consumers, and `LISTEN`/`NOTIFY` is a useful
  wakeup channel while structured data remains in tables.

Do not start with NATS unless writing lease/queue logic becomes the bottleneck.
NATS JetStream is a strong alternative because it has durable streams,
acknowledgements, and at-least-once delivery, but SASE still needs queryable run
state, artifacts, leases, and product APIs.

## Alternatives Rejected

**SSH as the product architecture.** Fastest proof of concept, but it requires
controller reachability to every worker and couples execution to the controller.
Keep it as a diagnostic transport only.

**Syncthing/Git inbox queue.** Fine for mirroring artifacts or project-local
state, but file sync does not create distributed locks, cancellation, lease
fencing, host routing, or stale-worker recovery.

**CI systems as the runtime.** GitHub Actions, Buildkite, and similar systems
are useful prior art, but SASE prompts, HITL flows, ChangeSpecs, credentials,
and artifacts need a SASE-native product model. CI can run isolated batch jobs;
it should not be the default personal-agent backend.

**Temporal or Nomad first.** Both are credible orchestration systems. They are
heavier than needed for a personal always-online endpoint and still require
SASE-specific workspace, prompt, artifact, and credential models.

**Public tunnel first.** Cloudflare Tunnel can create outbound-only origin
connections and is useful when non-tailnet access is unavoidable. It should be a
fallback with Access/service-token policy, not the default.

## Implementation Sequence

1. **Tailnet foundation.** Put every participating machine on Tailscale or
   WireGuard. Keep the gateway/broker private.
2. **Remote execution-host mode.** Run `sase mobile gateway start` on the
   always-online server, expose it with Tailscale Serve, and add thin
   laptop-friendly CLI glue for submit/list/kill/retry against that gateway.
3. **Identity and handles.** Land GitHub-first canonical project identity and
   add host-qualified fields to launch/artifact metadata. Start displaying
   `pid@host` or `run@host` where available.
4. **Loopback broker MVP.** Add `sase remote server` and `sase remote worker`
   on one machine. The worker claims from the server, supervises a foreground
   runner, mirrors minimal artifacts, and proves the visible outcome matches a
   local launch.
5. **One remote GitHub worker.** Run the server on the always-online host and a
   self-credentialed worker on a second machine. Support GitHub materialization,
   logs, cancel, stale heartbeat detection, and small artifact mirroring.
6. **Multi-worker scheduling.** Add host labels, capacity, priority, project
   pinning, retry classes, retention, pruning, and explicit remote artifact
   fetch.

Shared server behavior belongs in `../sase-core` per the Rust core backend
boundary. Python should stay the launch/runner glue and bridge into the Rust
server through narrow adapters.

## Sources

Local:

- `docs/mobile_gateway.md`
- `docs/mobile_mvp_runbook.md`
- `src/sase/integrations/mobile_gateway.py`
- `src/sase/core/agent_launch_wire.py`
- `src/sase/core/agent_launch_facade.py`
- `src/sase/agent/launch_spawn.py`
- `src/sase/axe/run_agent_runner.py`
- `src/sase/running_field/_model.py`
- `src/sase/ace/hooks/processes.py`
- `memory/short/rust_core_backend_boundary.md`
- `sdd/research/202606/apollo_remote_agents_workspace_topology.md`
- `sdd/research/202605/multi_machine_sync.md`
- `sdd/research/202605/same_named_github_repos.md`
- `sdd/research/202604/sase_web_client_research.md`

External:

- Tailscale Serve: <https://tailscale.com/docs/features/tailscale-serve>
- Buildkite agent polling model: <https://buildkite.com/docs/agent>
- GitHub self-hosted runner communication: <https://docs.github.com/en/actions/reference/runners/self-hosted-runners>
- Temporal task queues: <https://docs.temporal.io/task-queue>
- PostgreSQL `SELECT ... SKIP LOCKED`: <https://www.postgresql.org/docs/current/sql-select.html>
- PostgreSQL `NOTIFY`: <https://www.postgresql.org/docs/current/sql-notify.html>
- NATS JetStream: <https://docs.nats.io/nats-concepts/jetstream>
- Cloudflare Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/>

## Recommended Solution

Build remote agents in two steps: first run the existing SASE mobile gateway on
the always-online server behind Tailscale Serve so other devices can submit and
monitor agents that execute on that server; then, after GitHub-first canonical
project identity and host-qualified run handles are in place, add a SASE-native
pull broker in `sase-core`.

The broker should expose narrow controller and worker APIs, keep durable run
state and leases in a server-owned SQL store, issue fenced lease epochs, and run
self-credentialed `sase worker` processes that connect outbound, claim jobs,
supervise the whole SASE runner locally, stream logs, and mirror small artifacts.
Use SQLite for the single-process MVP to preserve the single-binary self-hosted
shape, design the schema so PostgreSQL can replace it for larger multi-worker
deployments, and use NATS JetStream only if broker correctness or fan-out
requirements outgrow the built-in queue.
