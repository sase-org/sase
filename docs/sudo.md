# Sudo Requests

SASE sudo requests let an agent ask for reviewed privileged execution without ever
asking for, receiving, logging, or proxying a password. The agent submits a typed batch
of exact argv commands, SASE creates a durable `sudo` gate, and a human reviews the
request before authenticating in a real terminal with the host's normal PAM prompt.

## Overview

A sudo request moves through four steps:

1. An agent finishes all non-root preparation, then pipes one JSON request to
   `sase sudo request`. SASE validates it, snapshots the SHA-256 of every executable,
   seals the reviewed command manifest, and creates a `sudo` gate backed by a
   [gate shell](notifications.md#gate-shells-and-continuation). The shell shows the
   `SUDO` status, and the agent's turn ends.
2. A reviewer opens the request in sase's TUI, checks the commands, and chooses which
   ones to run.
3. `sase sudo answer` authenticates through the real `sudo` prompt in a terminal. The
   dedicated `sase_sudo_runner` executes the selected commands and returns a ledger.
4. The gate settles as `SUDOED` (approved) or `DENIED`. After an approval, the request's
   `next.prompt` launches a successor in the same agent family that receives the ledger.
   A denial never launches a follow-up.

Agents learn this contract from the generated `/sase_sudo` skill.

## Enable The Workflow

Sudo requests are a beta feature behind the `agent_sudo_requests` feature flag, which is
off by default. While it is off, every `sase sudo` subcommand fails with
`feature_disabled`. Enable it persistently on each machine that creates, answers, or
executes sudo requests:

```bash
sase flag enable agent_sudo_requests
```

Use the persisted setting rather than a per-invocation `-f agent_sudo_requests`. When
you approve from sase's TUI, its terminal handoff does not pass along the TUI's own
resolved flag snapshot, so `sase sudo answer` resolves the flag afresh from the
machine's saved choice and configuration.

Approval also needs the `sase_sudo_runner` entry point that ships with SASE's Rust core
package. SASE looks for it next to the running Python interpreter first, then on `PATH`.

## Agent Contract

Agents must do all non-root preparation first, then batch the root work into one
`sase sudo request` JSON object on stdin. Each command needs a stable `id`, an exact
`argv` array whose executable is an absolute path, and a short `why` that explains why
root is needed.

| Field                  | Default           | Meaning                                                                                   |
| ---------------------- | ----------------- | ----------------------------------------------------------------------------------------- |
| `reason`               | required          | Why the batch needs root. Reviewers see it as untrusted agent text.                       |
| `commands`             | required          | Non-empty array of commands, run in the listed order.                                     |
| `run_as`               | `root`            | Target user.                                                                              |
| `cwd`                  | current directory | Existing absolute working directory for the commands.                                     |
| `env`                  | `{}`              | Reviewed string environment variables.                                                    |
| `machine`              | this host         | Enrolled machine alias or SSH target; see [Remote Flow](#remote-flow).                    |
| `stop_on_failure`      | `true`            | Skip the remaining commands after one fails.                                              |
| `output_to_agent`      | `tail`            | Command output passed to the successor: `none`, `tail`, or `full`.                        |
| `gate_timeout_seconds` | `300`             | Review window in whole seconds (at most one day).                                         |
| `timeout_seconds`      | none              | Default per-command timeout; also the review window when `gate_timeout_seconds` is unset. |
| `next.prompt`          | none              | Prompt for the successor that receives the ledger after approval.                         |

The working directory must be an existing absolute directory when the request is
created. At execution time, the runner changes the sudo child process into that
directory before invoking `/usr/bin/sudo`; it does not pass sudo's `-D` or `--chdir`
option. The directory must be accessible on the execution host to the user who is
authenticating. Normally the approved command inherits that directory, but sudoers
`CWD`/`runcwd` policy remains authoritative. SASE does not fall back to the runner's
directory or use root privileges to enter root-only directories.

The review window is short by default. A request nobody answers within
`gate_timeout_seconds` settles as timed out and launches no follow-up, so set a longer
window when the reviewer may not be at a terminal.

Each command accepts `id`, `argv`, `why`, and an optional `timeout_seconds` (at most one
day). Command IDs are 1–64 letters, digits, `.`, `_`, or `-`, start with a letter or
digit, and must be unique within the request. Omitting `machine`, or setting it to `""`
or `"local"`, targets the current host.

Agents must not run raw `sudo`, `doas`, `pkexec`, `su`, askpass helpers, shells, or
interactive root programs. Request validation enforces that boundary and rejects:

- nested privilege tools: `sudo`, `sudoedit`, `su`, `doas`, `pkexec`, and `run0`;
- shells and interactive programs (`sh`, `bash`, `dash`, `zsh`, `fish`, `ssh`, `vi`,
  `vim`, `nano`, `less`, `more`, `top`, and `htop`), plus any command with a bare `-c`
  argument;
- executables that are relative, missing, not a regular file, or writable by the
  requesting user;
- credential-shaped data: argv or environment values containing `password=`, `passwd=`,
  `passphrase=`, `secret=`, or `token=`, and environment keys containing those words;
- loader and askpass variables: `LD_*`, `DYLD_*`, `PYTHONPATH`, `PYTHONINSPECT`,
  `SUDO_ASKPASS`, and `SSH_ASKPASS`.

If output may be secret-adjacent, set `"output_to_agent": "none"` so the follow-up
prompt receives only the execution outcome.

Example:

```json
{
  "reason": "Install the reviewed sysctl policy file and apply it now.",
  "cwd": "/",
  "commands": [
    {
      "id": "install-policy",
      "argv": [
        "/usr/bin/install",
        "-o",
        "root",
        "-g",
        "root",
        "-m",
        "0644",
        "/tmp/sase-ptrace-scope.conf",
        "/etc/sysctl.d/99-sase-ptrace-scope.conf"
      ],
      "why": "Persist the reviewed ptrace policy as a root-owned sysctl drop-in."
    },
    {
      "id": "apply-policy",
      "argv": ["/usr/sbin/sysctl", "-p", "/etc/sysctl.d/99-sase-ptrace-scope.conf"],
      "why": "Apply the reviewed ptrace policy immediately."
    }
  ],
  "next": {
    "prompt": "Verify the sudo ledger, then check sysctl kernel.yama.ptrace_scope."
  }
}
```

`sase sudo request` prints a JSON gate descriptor. Inside an agent, it then hands the
turn to the gate shell, so run it in the foreground and treat the descriptor as the only
proof that the gate exists. Use `-o/--origin-agent` to attribute a request created
outside an agent.

## Review UX

In sase's TUI, a pending request appears on the Agents tab as a gate-shell row with the
`SUDO` status and in the notification inbox as a sudo request. Its notification carries
the `sudo` and `gate` tags and no declared panel, so it lands in a `sudo` tag tab rather
than `Gates`. Selecting the notification opens the **Sudo Request** review modal:

- **Context** lists the agent's reason, the target host, run-as user, working directory,
  environment policy, requester, project, expiry, and risk badges. The reason is treated
  as untrusted text.
- **Commands** is a checklist of every reviewed command, all selected by default.
  Approval runs only the selected commands, in their reviewed order.
- **Details** (`v`) shows each command's argv and executable SHA-256, the reviewed
  environment, timeout, stop and output policies, and the manifest SHA-256.
- **Denial Feedback** holds an optional note for the requesting agent.

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `Space`             | Toggle the focused command                   |
| `v`                 | Show or hide details                         |
| `Enter`             | **Authenticate & run** the selected commands |
| `d`                 | Deny, sending the feedback note              |
| `Ctrl+D` / `Ctrl+U` | Scroll half a page                           |
| `g` / `G`           | Jump to the top / bottom                     |
| `q` / `Esc`         | Close without answering                      |

Inside this modal `d` denies the request. To open Gate Debug, press `d` on the
notification row instead.

The approve action is **Authenticate & run**. It suspends sase's TUI, prints a banner
naming the request and the selected command IDs, and runs
`sase sudo answer <id> --run --json` (with one `--command` per selected ID) attached to
the controlling terminal. The only credential prompt is the real prompt printed by
`/usr/bin/sudo` or by the target host over SSH. When the command exits, sase's TUI shows
the outcome: completed, a selected command failed, authentication failed, cancelled, or
timed out, another sudo handoff is active, or no trusted terminal was available. Deny
runs through the normal gate path and needs no terminal because it runs no privileged
command.

Only `sase sudo answer` can approve a sudo gate. Every other answer path, including
`sase gate answer`, mobile, Telegram, fleet bridges, and detached procs, is refused and
leaves the gate pending. Those surfaces can still display or deny the request, and
`sase gate show` points at `sase sudo answer <id>`.

## Terminal Commands

| Command                        | Flags                                                                                                                     | Behavior                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `sase sudo` / `sase sudo list` | `-a/--all`, `-j/--json`, `-l/--limit`, `-p/--project`                                                                     | List pending sudo gate shells; `--all` includes settled ones.              |
| `sase sudo show ID`            | `-j/--json`                                                                                                               | Show one gate; `--json` adds the sealed manifest, target, and risk badges. |
| `sase sudo request`            | `-j/--json`, `-o/--origin-agent`                                                                                          | Create a sudo gate from one JSON object on stdin.                          |
| `sase sudo answer ID`          | `-u/--run` or `-a/--approve`, `-d/--deny`, `-c/--command ID`, `-f/--feedback`, `-j/--json`, `-r/--resume`, `-R/--restart` | Approve (authenticate and run) or deny one gate.                           |

`ID` is a sudo gate ID such as `sudo-<uuid>` or a gate-shell reference. `--run` and
`--approve` both authenticate and run. `--command` is repeatable and selects a subset of
the reviewed commands; without it, every command runs. Without `--run`, `--approve`, or
`--deny`, an interactive terminal asks `Approve sudo request? [y/N]`. A non-interactive
call must choose explicitly, and approval always requires a controlling terminal.

With `--json`, a failed answer prints `status: "pending"` plus an `outcome` of
`authentication_failed`, `cancellation`, `timeout`, `lock_contention`, `missing_tty`, or
`runner_error`. It exits `2` for the first five outcomes and `1` for `runner_error`.

Only one sudo authentication handoff runs at a time on a host. A second attempt fails
immediately and names the request, user, and process that hold the lease. The runner
receives the sealed manifest in a private temporary file together with its expected
hash. Its overall timeout is the sum of the selected commands' timeouts (300 seconds for
each command without one) plus 30 seconds.

SASE accepts the runner's ledger only when it matches the reviewed manifest hash,
contains exactly one entry per selected command, and carries no credential-shaped data.
A command that fails after authentication does not keep the gate pending. The gate still
settles as approved, the ledger records each command's status, and sase's TUI warns that
a selected command failed. With `stop_on_failure`, the remaining commands do not run.
The successor reads the ledger and decides what to do next.

## Remote Flow

For a machine-targeted request, set `machine` to an enrolled alias or an SSH target. An
enrolled alias resolves to its recorded SSH handoff target, which defaults to the alias
itself (`sase machine show ALIAS` prints it). Any other value must be a valid SSH
destination and is shown to the reviewer as an unenrolled host.

Review still happens on the controller. On approval, the controller:

1. checks that `ssh <target> sase sudo exec --contract` reports a compatible contract;
2. stages the sealed manifest in a private temporary file under the target's `/tmp`;
3. runs `ssh -t <target> sase sudo exec ...`, so the target's own runner prompts for
   authentication inside the SSH terminal;
4. reads the target's JSON ledger back and removes both temporary files.

The target needs `sase` on its non-interactive SSH `PATH`, its own `sase_sudo_runner`,
and `agent_sudo_requests` enabled, because `sase sudo exec` is behind the same flag. The
PAM conversation stays inside the SSH terminal channel between the reviewer and the
target machine; the fleet gateway never carries password material.

The local gate settles from the returned ledger. If the target is unreachable, has no
compatible `sase sudo exec`, lacks a TTY, or produces no ledger, the gate remains
pending and can be retried.

## Policy Rationale

The sudo request flow replaces standing passwordless sudo with an explicit review and
authentication boundary. SASE records the request, selected command IDs, manifest hash,
bounded command output, and runner ledger. It never records the password, password
length, password digest, PAM transcript, attempt count, or any derived credential
material.

Commands are hash-bound from review to execution. Bundle-owned option commands are
rehashed immediately before execution, and the sudo runner verifies the manifest hash
before running anything. After a batch settles, the runner invalidates the sudo
timestamp so approval does not create reusable ambient privilege.

## Recovery

A pending sudo gate can be inspected with:

```bash
sase sudo list
sase sudo show <id>
```

If approval fails because authentication was cancelled, a password attempt failed, a
timeout occurred, no TTY was available, another handoff held the lease, or the runner
could not be found, the gate remains pending. Re-run:

```bash
sase sudo answer <id> --run
```

If a ledger shows sudo rejected `-D` or `--chdir`, the host ran an old sudo runner. The
reviewed command never reached the package manager or other target executable. Changing
or omitting `cwd` in a new request does not repair that old runner, because request
normalization always supplies a cwd and the old runner always translated it to sudo
`-D`. After installing a fixed runner, create a new reviewed sudo request for any
already-settled failed approval instead of trying to reuse the old gate.

Every approval runs the full selected command set again. If a run was interrupted
partway, for example by the runner timeout, no ledger is recorded and some commands may
already have taken effect. Check the host, then select only the commands that still need
to run:

```bash
sase sudo answer <id> --run --command apply-policy
```

`--resume` and `--restart` are accepted for parity with `sase gate answer`, but they do
not make the runner skip commands that already ran.

During host policy changes, keep an already-authenticated root escape hatch open until
the reviewed change has been applied and verified. If a lockout risk appears, use that
terminal to restore the last known-good sudoers or sysctl state, then leave the sudo
gate pending with an evidence note rather than bypassing the reviewed flow silently.
