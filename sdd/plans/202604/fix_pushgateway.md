---
create_time: 2026-04-08 21:11:30
status: wip
prompt: sdd/prompts/202604/fix_pushgateway.md
---

# Plan: Diagnose and Fix Prometheus Push Gateway

## Root Cause

The Prometheus Push Gateway is reported as "not reachable" by `sase telemetry status`. Upon diagnosis, the `pushgateway`
binary is neither installed via the system package manager (`apt`) nor via Docker, and `docker`/`podman` themselves are
not installed on this machine. Since we don't have `sudo` access to install packages system-wide, we must deploy it
locally for the user.

## Implementation Plan

We will download the official Prometheus Push Gateway binary, place it in the user's local bin directory, and set up a
user-level `systemd` service to ensure it runs continuously in the background on `localhost:9091`.

### Steps

1. **Download the Binary:** Fetch `pushgateway-1.9.0.linux-amd64.tar.gz` from the official Prometheus GitHub releases.
2. **Install:** Extract the tarball and move the `pushgateway` executable to `~/.local/bin/`.
3. **Configure User Systemd Service:** Create a systemd unit file at
   `~/.config/systemd/user/prometheus-pushgateway.service` to manage the process.
4. **Enable and Start:** Reload the systemd user daemon, enable, and start the new `prometheus-pushgateway` service.
5. **Validation:** Run `sase telemetry status` to verify the Push Gateway is now reachable.
