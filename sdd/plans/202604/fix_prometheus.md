---
create_time: 2026-04-08 21:22:45
status: wip
prompt: sdd/prompts/202604/fix_prometheus.md
---

# Plan: Diagnose and Fix Prometheus

## Root Cause

The `sase telemetry dashboard -c` command attempts to fetch historical metric data from the Prometheus server on
`localhost:9090` (by default). However, the dashboard is reporting that "Prometheus is not reachable — falling back to
summary mode."

Upon investigation, the Prometheus service is not running on port 9090. Furthermore, Docker is not installed on this
machine, meaning the bundled docker-compose monitoring stack cannot be used. Similar to the pushgateway issue
(`plans/202604/fix_pushgateway.md`), we need to install the Prometheus binary locally and configure it as a systemd user
service.

## Implementation Plan

We will download the official Prometheus binary, place it in the user's local bin directory, configure it using the
exported SASE prometheus config, and set up a user-level `systemd` service to ensure it runs continuously in the
background on `localhost:9090`.

### Steps

1. **Download the Binary:** Fetch the latest `prometheus-2.51.1.linux-amd64.tar.gz` (or similar recent version) from the
   official Prometheus GitHub releases.
2. **Install:** Extract the tarball and move the `prometheus` executable to `~/.local/bin/`.
3. **Configure Prometheus:** Copy the SASE bundled `prometheus.yml` (and `alerts.yml`) to a local configuration
   directory (e.g., `~/.config/prometheus/`).
4. **Configure User Systemd Service:** Create a systemd unit file at `~/.config/systemd/user/prometheus.service` to
   manage the process, pointing it to the configuration directory and a local data directory (e.g.,
   `~/.local/share/prometheus`).
5. **Enable and Start:** Reload the systemd user daemon, enable, and start the new `prometheus` service.
6. **Validation:** Run `curl http://localhost:9090/-/ready` to verify Prometheus is running, and test the
   `sase telemetry dashboard -c` command.
