#!/usr/bin/env bash
set -u
out=.sase-evidence/report_athena_sase_latest.json
meta=.sase-evidence/report_athena_sase_latest.meta
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'host=athena\nproject=sase\ncommand=sase agent sync --repair-revisions --project sase --json\nstarted_utc=%s\n' "$started" > "$meta"
ssh -T athena 'zsh -lic "bash -s"' < .sase-evidence/remote_report_athena.sh > "$out" 2> "$out.stderr"
rc=$?
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'finished_utc=%s\nexit_code=%s\n' "$finished" "$rc" >> "$meta"
sha256sum "$out" >> "$meta"
cat "$out.stderr" >> "$meta"
printf 'report_file=%s\n' "$out"
printf 'meta_file=%s\n' "$meta"
exit "$rc"
