# Sudo Requests

SASE sudo requests let an agent ask for reviewed privileged execution without ever
asking for, receiving, logging, or proxying a password. The agent submits a typed batch
of exact argv commands, SASE creates a durable `sudo` gate, and a human reviews the
request before authenticating in a real terminal with the host's normal PAM prompt.

## Agent Contract

Agents must do all non-root preparation first, then batch the root work into one
`sase sudo request` JSON object. Each command needs a stable `id`, an exact `argv` array
whose executable is an absolute path, and a short `why` that explains why root is
needed. Requests can set `run_as`, `cwd`, reviewed `env`, `machine`, `stop_on_failure`,
`output_to_agent`, and a `next.prompt` for the successor agent that receives the ledger.

Agents must not run raw `sudo`, `doas`, `pkexec`, `su`, askpass helpers, shells, or
interactive root programs. If output may be secret-adjacent, set
`"output_to_agent": "none"` so the follow-up prompt receives only the execution outcome.

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

## Review UX

ACE shows sudo requests as terminal-only review gates with a SUDO status and a sudo
panel. The modal lists the target host, run-as user, working directory, environment
policy, requester, manifest hash, risk badges, and every reviewed command. The agent's
reason is treated as untrusted text.

The approve action is **Authenticate & run**. It suspends ACE, prints a host-authored
banner, and runs `sase sudo answer <id> --run` attached to the controlling terminal. The
only credential prompt is the real prompt printed by `/usr/bin/sudo` or the target host
over SSH. Deny remains available from headless surfaces because it runs no privileged
command.

Headless answer paths, mobile, Telegram, fleet bridges, and detached procs cannot
approve sudo gates. They display the request and the `sase sudo answer <id>` hint, then
leave the gate pending if approval is attempted without a TTY.

## Remote Flow

For a machine-targeted request, set `machine` to an enrolled alias or SSH target. Review
still happens on the controller. On approval, SASE opens `ssh -t <target>` and asks the
target to run `sase sudo exec` with the sealed manifest. The PAM conversation stays
inside the SSH terminal channel between the reviewer and the target machine; the fleet
gateway never carries password material.

The target returns a JSON ledger to the controller, and the local gate settles from that
receipt. If the target is unreachable, has no compatible `sase sudo exec`, lacks a TTY,
or produces no ledger, the gate remains pending and can be retried.

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
timeout occurred, or no TTY was available, the gate remains pending. Re-run:

```bash
sase sudo answer <id> --run
```

When a batch partially ran and then failed, SASE records a partial attempt. Use
`--resume` to continue after the completed command IDs, or `--restart` to run the
reviewed branch from the beginning:

```bash
sase sudo answer <id> --run --resume
sase sudo answer <id> --run --restart
```

During host policy changes, keep an already-authenticated root escape hatch open until
the reviewed change has been applied and verified. If a lockout risk appears, use that
terminal to restore the last known-good sudoers or sysctl state, then leave the sudo
gate pending with an evidence note rather than bypassing the reviewed flow silently.
