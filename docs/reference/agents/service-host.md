---
title: Service host initialization
description: Look up how SASE initializes its per-user service host.
---

# Service host initialization

This page describes the service host initializer and its environment snapshot.

## Service host

Service initialization installs a per-user systemd unit on Linux or a per-user
LaunchAgent on macOS, plus a mode-`0600` environment snapshot containing only the
allowlisted variables needed by the host. The preview is the default:

```bash
sase service init
sase service init --check
sase service init --diff
sase service init --yes
```

`--check` and `--diff` never write. Apply retires recognized legacy service units and
reloads the platform manager. Linux reports when user lingering is disabled because the
unit then stops with the login session. A non-default `SASE_HOME` changes the native
unit identity and therefore requires `--force`; the command prints the resulting
home-scoped identity before applying it. Use `sase service uninstall` with the same
preview, check, diff, force, and confirmation model to remove the managed unit.

Currency compares only what the host depends on. `SSH_AUTH_SOCK` and `SSH_AGENT_PID` are
ignored, and `PATH` is normalized before comparison: empty and duplicate entries are
stripped, trailing slashes are removed, and ephemeral `sase_<N>` workspace entries are
dropped. A real credential, root, or `PATH` change still rewrites the file.

`SASE_TMPDIR` and `SASE_HOME` are captured so the service host's `managed_tmp_reap` job
scans the same managed temp root that launched agents write to. A capture taken with a
different (or no) `SASE_TMPDIR` than the shell running the check shows up in
`sase service init --check` only as ordinary environment drift (a pending rewrite of the
captured environment file, exit `1`); there is no dedicated temp-root warning. Rerun
`sase service init --yes` from a shell with the intended `SASE_TMPDIR` to realign them.
The reaper job itself also logs a warning when it scans a captured `SASE_TMPDIR` root
while the default `$SASE_HOME/tmp` root still holds entries; see
[the `housekeeping` routine](../automation/scheduler-housekeeping.md#housekeeping-1-hour-interval)
for what that warning does and does not catch.

`init --yes` refuses a SASE agent process. When the calling shell sets `SASE_AGENT` or
`SASE_AGENT_NAME`, or its `PATH` contains an ephemeral workspace entry, apply exits 2
and names a login shell as the fix. Pass `-a/--allow-agent-env` (on both
`sase service init` and the `sase init service` alias) to capture deliberately.
`--check` and `--diff` stay available everywhere; only the capture-and-write path is
guarded.

The captured environment includes the SSH agent handle (`SSH_AUTH_SOCK`, plus
`SSH_AGENT_PID` when present) whenever it names a live socket. That is a convenience,
not a durable credential: an agent socket captured from a login shell
(`/tmp/ssh-*/agent.*`) belongs to that session and dies with it. At host start, a
captured agent socket that is missing is ignored and the manager's agent applies — on
Linux that is the systemd user manager's `SSH_AUTH_SOCK`, often a live but empty socket.
A captured login-shell socket is still not a durable credential. Do not count on it to
keep host-owned git work, such as plan archival from a Telegram approval, authenticated
across a reboot or a new login session.

Readiness is decided by the git remote, not by what an agent holds.
`sase service init --check`, `sase service status`, and plan approvals each ask the
remote to authenticate (`ssh -o BatchMode=yes -T git@github.com`) using the environment
in question, and only a refusal warns: `Permission denied (publickey)`, or a login that
GitHub greets as a deploy key (`Hi <owner>/<repo>!`), which it scopes to that one
repository so every other push fails with `denied to deploy key`. A host that
authenticates by `IdentityFile` is healthy even though its agent is empty or absent, and
a host that cannot reach the network is reported as unknown rather than as a credential
failure. `sase service status` (and `sase service init --check` for an installed unit)
reports on both the environment `init` is about to capture and the _effective_ one: the
captured file overlaid on what the manager hands the unit. A working credential in your
own shell cannot mask a refused one in the service.

Durability is a separate warning. When the checked environment authenticates through a
login-session agent but the same environment without that agent is refused,
`sase service init`, `--check`, `sase service status`, and the doctor check warn that
the service host's only accepted credential is that login-session agent. After a reboot
or logout the host falls back to the manager's agent (or no agent), which the git remote
refuses. The warning names the login-session socket and the fallback, points here for an
unattended credential, and reports captured and effective scopes separately. It stays
silent when either probe is unknown, when the agent already is the manager's, and when
an `IdentityFile` lets the fallback authenticate.

A plan approval that archives the plan (the `commit` option) runs the same check before
the decision is accepted. If the remote refuses the credential, the answer is refused
with the remediation and the gate stays pending, instead of being accepted and then
failing at `terminal_prepare`. An unknown answer never blocks an approval.

While the credential is refused, host chops that write beads cannot fetch their
operational workspace, so they fail with `Permission denied (publickey)`. The external
issue mirror treats this as a credential failure: it reports `auth_error`, logs the git
error, and backs off exponentially instead of failing on every scheduled tick. Beads are
not mirrored until the credential is restored. Operational lease preparation retries a
transient transport failure (connection reset, timeout, DNS) up to three attempts. It
re-checks a `Permission denied (publickey)` once after about 10 seconds before failing,
so a brief remote-side refusal, such as during a GitHub incident, can recover before the
leased operation fails. A refusal that survives the re-check is reported with the
existing remediation.

The code cannot restore the credential, so this is yours to fix. There are two supported
ways to give the host an unattended credential:

1. **Dedicated passphrase-less key via `IdentityFile` (preferred).** Generate an ed25519
   key used only by the service host, add its public key to the GitHub account, and
   point the `Host github.com` block of `~/.ssh/config` at it, keeping
   `IdentitiesOnly yes` (without it ssh offers every agent key before the file, and when
   one is a deploy key for another repository GitHub accepts it at login and then
   refuses every other repository with `Permission to <repo> denied to deploy key`):

   ```bash
   ssh-keygen -t ed25519 -N "" -C "sase-service@$(hostname)" -f ~/.ssh/id_sase_service
   ```

   ```
   IdentityFile ~/.ssh/id_sase_service
   IdentitiesOnly yes
   ```

   It is fully unattended, survives reboots and logout, and needs no agent. Verify it
   without any agent:
   `env -u SSH_AUTH_SOCK -u SSH_AGENT_PID ssh -o BatchMode=yes -T git@github.com`. Then
   run `ssh -T git@github.com` from a login shell whose agent holds your other keys: it
   must greet your account (`Hi <login>!`), not a repository (`Hi <owner>/<repo>!`). A
   key protected by a passphrase cannot serve here, because nothing can type the
   passphrase.

   When `~/.ssh/config` is shared across machines, guard the identity so machines
   without the key are unaffected. Insert this directly after the existing
   `Host github.com` block instead of editing that block:

   ```
   # SASE service host unattended GitHub credential (sase docs/reference/agents/service-host.md).
   # No-op on machines without the key.
   Match originalhost github.com exec "test -r %d/.ssh/id_sase_service"
     IdentityFile ~/.ssh/id_sase_service
     IdentitiesOnly yes
   ```

2. **Load a key into the systemd user agent (interim).** Run
   `SSH_AUTH_SOCK=<the reported socket> ssh-add <your private key>`, using the socket
   the service host inherits rather than your shell's. It survives logout when lingering
   is enabled, but not a reboot, and needs your passphrase once per boot. After a reboot
   load the key into the manager's agent again with `ssh-add`; a missing capture lets
   the manager's agent handle authentication.

After either, run `sase service init` and `sase service restart`, and confirm
`sase service status` reports no SSH warning.

`sase service init` also warns when an enabled `command:` entry in `service.procs` names
an executable that the host would fail to spawn. A bare first element is looked up on
the captured `PATH`, then next to the interpreter running SASE; the warning appears only
when both miss, and names the executable and the directory searched. The usual cause is
a plugin's console script under `uv tool install --with`, which does not link plugin
scripts onto `PATH`. Install the plugin into the same environment as `sase`, or give the
entry an absolute path. Without the warning the host would only report the failure after
repeated spawn failures, as a `crash_loop` proc in `sase service status` plus a
`service` notification (or, under `restart: never`, as a parked `exited` proc).

Bare `sase init` offers this machine-scoped initializer at most once per batch. A
decline is remembered for future broad onboarding runs on that machine, but it does not
disable the service feature or suppress an explicit `sase service init`.

## Related

- [Agents and workspaces](index.md) — the section hub.
