#!/usr/bin/env python3
"""Execute one Rust-selected release-steward train action.

The caller supplies a ``recheck`` callback that rebuilds the complete snapshot
and calls ``release_steward_decide`` again immediately before each write. This
module owns only transport execution and restart-safe action mechanics; it
does not calculate release policy.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from _release_watch_transport import (
    GH_TIMEOUT_SECONDS,
    GithubTransport,
    PypiTransport,
    run_process,
)


ACTION_TIMEOUT_SECONDS = 60.0
ABANDONED_TITLE_PREFIX = "[ABANDONED] "


class ActionExecutionError(RuntimeError):
    """A train mutation failed or its acknowledgement is uncertain."""

    def __init__(
        self,
        source: str,
        message: str,
        *,
        remedy: str = "re-read remote facts and reconcile before another attempt",
        uncertain: bool = False,
    ) -> None:
        self.source = source
        self.remedy = remedy
        self.uncertain = uncertain
        super().__init__(message)


Recheck = Callable[[], tuple[Mapping[str, Any], Mapping[str, Any]]]


def _wire_action(action: object) -> dict[str, Any]:
    if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
        raise ActionExecutionError("action", "train action is malformed")
    return action


def _expected_argv(action: Mapping[str, Any]) -> list[str]:
    kind = action["kind"]
    if kind == "merge_release_pr":
        return [
            "gh",
            "pr",
            "merge",
            str(action["pr_number"]),
            "--merge",
            "--match-head-commit",
            str(action["head_sha"]),
        ]
    if kind == "dispatch_release":
        mode = action["mode"]
        if mode not in {"release", "resume"}:
            raise ActionExecutionError("action", f"unsupported release mode {mode!r}")
        return [
            "gh",
            "workflow",
            "run",
            "release.yml",
            "--ref",
            str(action["tag"]),
            "-f",
            f"mode={mode}",
        ]
    if kind == "dispatch_publish_metadata":
        return ["gh", "workflow", "run", "publish.yml"]
    if kind == "rerun_failed_jobs":
        return ["gh", "run", "rerun", str(action["run_id"]), "--failed"]
    if kind == "dispatch_core_cut":
        return [
            "gh",
            "workflow",
            "run",
            "release-plz.yml",
            "-f",
            "dry_run=false",
        ]
    if kind == "abandon_candidate":
        return []
    raise ActionExecutionError("action", f"unsupported train action {kind!r}")


def _same_train_action(expected: object, actual: object) -> tuple[bool, str]:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False, "the Rust policy no longer proposes this train action"
    if actual.get("disposition") != "proposed":
        return False, str(actual.get("reason") or "the action is no longer proposed")
    if expected.get("key") != actual.get("key"):
        return False, "the train action key changed during revalidation"
    for key in ("action", "preconditions", "argv"):
        if expected.get(key) != actual.get(key):
            return False, f"the train action {key} changed during revalidation"
    return True, ""


def _same_escalation(expected: object, actual: object) -> tuple[bool, str]:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False, "the Rust policy no longer proposes this escalation"
    if actual.get("disposition") != "proposed":
        return False, str(
            actual.get("disposition") or "escalation is no longer proposed"
        )
    if expected.get("key") != actual.get("key"):
        return False, "the escalation key changed during revalidation"
    if expected.get("operation") != actual.get("operation"):
        return False, "the escalation operation changed during revalidation"
    return True, ""


def _repo_for(action: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    if action["kind"] == "dispatch_core_cut":
        return "sase-org/sase-core"
    snapshot = request.get("snapshot")
    repository = snapshot.get("repository") if isinstance(snapshot, dict) else None
    value = repository.get("value") if isinstance(repository, dict) else None
    if not isinstance(value, dict):
        raise ActionExecutionError("repository", "fresh repository identity is absent")
    owner, name = value.get("owner"), value.get("name")
    if not isinstance(owner, str) or not isinstance(name, str):
        raise ActionExecutionError(
            "repository", "fresh repository identity is malformed"
        )
    return f"{owner}/{name}"


def _gh_env(repo: str) -> dict[str, str]:
    return {
        "GH_REPO": repo,
        "GH_PROMPT_DISABLED": "1",
        "GH_NO_UPDATE_NOTIFIER": "1",
        "GH_FORCE_TTY": "0",
        "NO_COLOR": "1",
        "CLICOLOR": "0",
        "CLICOLOR_FORCE": "0",
        "FORCE_COLOR": "0",
    }


class ReleaseWatchActionExecutor:
    """Run the one train action chosen by Rust, after a fresh policy read."""

    def __init__(
        self,
        *,
        recheck: Recheck,
        runner: Callable[..., subprocess.CompletedProcess[str]] = run_process,
        github: Any | None = None,
        pypi: Any | None = None,
        repo: str = "sase-org/sase",
        run_id: int | None = None,
        attempt: int | None = None,
        candidate_script: Path | None = None,
        issue_runner: Any | None = None,
        timeout: float = ACTION_TIMEOUT_SECONDS,
    ) -> None:
        self.recheck = recheck
        self.runner = runner
        self.github = github or GithubTransport(repo)
        self.pypi = pypi or PypiTransport()
        self.repo = repo
        self.run_id = run_id
        self.attempt = attempt
        self.candidate_script = candidate_script or Path(__file__).with_name(
            "release_candidate"
        )
        self.issue_runner = issue_runner
        self.timeout = timeout

    def execute(
        self,
        decision: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        live: bool,
    ) -> dict[str, Any]:
        """Execute at most one train action and one issue operation.

        Read-only runs return the Rust result untouched and execute no
        subprocesses. For live runs, every logical mutation is gated by a
        fresh snapshot and a matching Rust decision.
        """
        result = copy.deepcopy(dict(decision))
        if not live or result.get("process_exit") == 1:
            return result
        try:
            planned = result.get("train_action")
            needs_train_recheck = (
                isinstance(planned, dict) and planned.get("disposition") == "proposed"
            ) or _has_abandoned_train(request)
            if needs_train_recheck:
                fresh_request, fresh_decision = self._recheck()
                repaired = self._repair_abandonment_title(fresh_request)
                if repaired is not None:
                    if (
                        isinstance(planned, dict)
                        and planned.get("disposition") == "proposed"
                    ):
                        _set_disposition(
                            planned,
                            "suppressed",
                            "restart recovery used this tick's train-action slot",
                        )
                    else:
                        result["train_action"] = repaired
                    result["details"] = _append_detail(
                        result.get("details", ""),
                        "reconciled an abandoned draft title left incomplete by an earlier tick",
                    )
                elif (
                    isinstance(planned, dict)
                    and planned.get("disposition") == "proposed"
                ):
                    current = fresh_decision.get("train_action")
                    same, reason = _same_train_action(planned, current)
                    if not same:
                        disposition = (
                            "already_satisfied"
                            if isinstance(current, dict)
                            and current.get("disposition") == "already_satisfied"
                            else "suppressed"
                        )
                        _set_disposition(planned, disposition, reason)
                    else:
                        self._execute_train(planned, fresh_request)
                        _set_disposition(planned, "executed", "action completed")

            escalation = result.get("escalation")
            if (
                isinstance(escalation, dict)
                and escalation.get("disposition") == "proposed"
            ):
                fresh_request, fresh_decision = self._recheck()
                current = fresh_decision.get("escalation")
                same, reason = _same_escalation(escalation, current)
                if not same:
                    disposition = (
                        "already_satisfied"
                        if isinstance(current, dict)
                        and current.get("disposition") == "already_satisfied"
                        else "suppressed"
                    )
                    _set_disposition(escalation, disposition, reason)
                else:
                    from _release_watch_sinks import ReleaseWatchIssueSink

                    sink_options: dict[str, Any] = {
                        "github": self.github,
                        "repo": self.repo,
                        "timeout": self.timeout,
                    }
                    if self.issue_runner is not None:
                        sink_options["runner"] = self.issue_runner
                    sink = ReleaseWatchIssueSink(**sink_options)
                    outcome, reason = sink.execute(
                        escalation,
                        fresh_request,
                        fresh_decision,
                        live=True,
                    )
                    _set_disposition(escalation, outcome, reason)
            return result
        except ActionExecutionError as exc:
            return _watcher_broken(result, exc)
        except Exception as exc:  # fail closed on unexpected adapter/transport errors
            return _watcher_broken(
                result,
                ActionExecutionError(
                    "action_executor",
                    f"unexpected execution error: {type(exc).__name__}: {exc}",
                    uncertain=True,
                ),
            )

    def _recheck(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            request, decision = self.recheck()
        except Exception as exc:
            raise ActionExecutionError(
                "action_revalidation",
                f"could not refresh facts before mutation: {type(exc).__name__}: {exc}",
                remedy="restore read access, then let the next tick recompute",
            ) from exc
        if not isinstance(request, Mapping) or not isinstance(decision, Mapping):
            raise ActionExecutionError(
                "action_revalidation",
                "revalidation did not return a request and decision",
            )
        if decision.get("primary", {}).get("kind") == "watcher_broken":
            primary = decision["primary"]
            raise ActionExecutionError(
                str(primary.get("source", "action_revalidation")),
                str(decision.get("details", "fresh facts are unreadable")),
                remedy=str(primary.get("remedy", "restore the failed fact source")),
            )
        return dict(request), dict(decision)

    def _run(
        self, argv: list[str], *, repo: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        if not argv or argv[0] != "gh":
            raise ActionExecutionError("action", "mutation argv must start with gh")
        try:
            proc = self.runner(
                argv,
                timeout=self.timeout,
                env=_gh_env(repo or self.repo),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ActionExecutionError(
                "action_acknowledgement",
                f"mutation acknowledgement is uncertain: {exc}",
                uncertain=True,
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            raise ActionExecutionError(
                "action_acknowledgement",
                "mutation returned an uncertain failure"
                + (f": {detail[:300]}" if detail else ""),
                uncertain=True,
            )
        return proc

    def _execute_train(
        self, wrapped: Mapping[str, Any], request: Mapping[str, Any]
    ) -> None:
        action = _wire_action(wrapped.get("action"))
        expected = _expected_argv(action)
        actual = wrapped.get("argv")
        if actual != expected:
            raise ActionExecutionError(
                "action_argv", "Rust action argv does not match its typed action"
            )
        if action["kind"] == "abandon_candidate":
            self._abandon(action, wrapped, request)
            return
        self._run(expected, repo=_repo_for(action, request))

    def _abandon(
        self,
        action: Mapping[str, Any],
        wrapped: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> None:
        candidate_id = _text(action.get("candidate_id"), "candidate_id")
        generation = _positive_int(action.get("generation"), "generation")
        expected_logical_asset = f"{candidate_id}.gen{generation}.abandoned.json"
        if action.get("observation_asset") != expected_logical_asset:
            raise ActionExecutionError(
                "abandonment",
                "abandonment observation key does not match candidate identity",
            )
        if not self.run_id or not self.attempt or self.run_id < 1 or self.attempt < 1:
            raise ActionExecutionError(
                "abandonment",
                "a positive workflow run ID and attempt are required for the observation",
            )

        train = _train_for(request, candidate_id, generation)
        version = _text(train.get("version"), "train.version")
        tag = _text(train.get("tag"), "train.tag")
        sha = _text(train.get("sha"), "train.sha")
        release = self._release_for_tag(tag)
        manifest = self._manifest(release, candidate_id, generation, version, tag, sha)
        self._require_zero_public_files(version)

        asset_name = (
            f"candidate-gen{generation}-abandoned-run{self.run_id}-"
            f"attempt{self.attempt}.json"
        )
        existing = _find_asset(release, asset_name)
        if existing is not None:
            observation = self.github.asset_json(
                _positive_int(existing.get("id"), "abandoned asset id"),
                source=f"release {tag} abandoned observation",
            )
            if not _valid_abandonment_observation(
                observation, candidate_id, generation, self.run_id, self.attempt
            ):
                raise ActionExecutionError(
                    "abandonment",
                    f"conflicting observation asset {asset_name} already exists",
                )
        else:
            observation_path, observation_dir = self._make_observation(
                manifest, wrapped, request
            )
            try:
                try:
                    self._run(
                        ["gh", "release", "upload", tag, str(observation_path)],
                        repo=self.repo,
                    )
                except ActionExecutionError as exc:
                    # Do not retry an uncertain upload. A fresh read can prove the
                    # side effect landed, allowing the title substep to resume.
                    if not exc.uncertain:
                        raise
                    reconciled = self._release_for_tag(tag)
                    uploaded = _find_asset(reconciled, asset_name)
                    if uploaded is None:
                        raise
                    observation = self.github.asset_json(
                        _positive_int(uploaded.get("id"), "abandoned asset id"),
                        source=f"release {tag} abandoned observation",
                    )
                    if not _valid_abandonment_observation(
                        observation, candidate_id, generation, self.run_id, self.attempt
                    ):
                        raise
            finally:
                shutil.rmtree(observation_dir, ignore_errors=True)
        self._require_zero_public_files(version)
        self._prefix_abandoned_title(tag)

    def _make_observation(
        self,
        manifest: dict[str, Any],
        wrapped: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> tuple[Path, Path]:
        snapshot = request.get("snapshot")
        candidate_fact = (
            snapshot.get("candidate") if isinstance(snapshot, dict) else None
        )
        candidate = (
            candidate_fact.get("value") if isinstance(candidate_fact, dict) else None
        )
        clauses = candidate.get("clauses", []) if isinstance(candidate, dict) else []
        extra = {
            "action_asset": wrapped.get("action", {}).get("observation_asset"),
            "observed_at": request.get("observed_at"),
            "evidence": [item for item in clauses if isinstance(item, dict)],
        }
        output_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(
                prefix="release-watch-abandon-"
            ) as raw_dir:
                directory = Path(raw_dir)
                manifest_path = directory / "manifest.json"
                extra_path = directory / "extra.json"
                observation_path = directory / "observation.json"
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True), encoding="utf-8"
                )
                extra_path.write_text(
                    json.dumps(extra, sort_keys=True), encoding="utf-8"
                )
                argv = [
                    sys.executable,
                    str(self.candidate_script),
                    "observe",
                    "--manifest",
                    str(manifest_path),
                    "--kind",
                    "abandoned",
                    "--run-id",
                    str(self.run_id),
                    "--attempt",
                    str(self.attempt),
                    "--verdict",
                    "abandoned",
                    "--reason",
                    str(wrapped.get("reason", "unrecoverable unpublished candidate")),
                    "--extra",
                    str(extra_path),
                    "--out",
                    str(observation_path),
                ]
                proc = self.runner(argv, timeout=self.timeout, env=None)
                if proc.returncode != 0:
                    detail = (
                        (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
                    )
                    raise ActionExecutionError(
                        "abandonment_observation",
                        "candidate observation creation failed"
                        + (f": {detail[:300]}" if detail else ""),
                    )
                payload = json.loads(observation_path.read_text(encoding="utf-8"))
                expected_name = (
                    f"candidate-gen{manifest['generation']}-abandoned-"
                    f"run{self.run_id}-attempt{self.attempt}.json"
                )
                if (
                    not _valid_abandonment_observation(
                        payload,
                        manifest["candidate_id"],
                        manifest["generation"],
                        self.run_id,
                        self.attempt,
                    )
                    or payload.get("asset") != expected_name
                ):
                    raise ActionExecutionError(
                        "abandonment_observation",
                        "candidate CLI produced an unexpected observation identity",
                    )
                retained = directory / expected_name
                retained.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                # The release asset's basename is part of the candidate
                # observation contract, so use a private directory and the
                # exact generation/run/attempt filename.
                output_dir = Path(tempfile.mkdtemp(prefix="release-watch-observation-"))
                output = output_dir / expected_name
                output.write_bytes(retained.read_bytes())
                return output, output_dir
        except ActionExecutionError:
            if output_dir is not None:
                shutil.rmtree(output_dir, ignore_errors=True)
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if output_dir is not None:
                shutil.rmtree(output_dir, ignore_errors=True)
            raise ActionExecutionError(
                "abandonment_observation", f"cannot build observation asset: {exc}"
            ) from exc

    def _release_for_tag(self, tag: str) -> dict[str, Any]:
        try:
            payload = self.github.json(f"repos/{self.repo}/releases/tags/{tag}")
        except Exception as exc:
            raise ActionExecutionError(
                "abandonment_release", f"cannot re-read draft release {tag}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("tag_name") != tag:
            raise ActionExecutionError(
                "abandonment_release",
                f"release lookup for {tag} returned a mismatched record",
            )
        if not isinstance(payload.get("draft"), bool):
            raise ActionExecutionError(
                "abandonment_release", f"release {tag} has no valid draft flag"
            )
        if not isinstance(payload.get("name"), str):
            raise ActionExecutionError(
                "abandonment_release", f"release {tag} has no valid title"
            )
        if not isinstance(payload.get("assets"), list):
            raise ActionExecutionError(
                "abandonment_release", f"release {tag} assets are malformed"
            )
        if not payload["draft"]:
            raise ActionExecutionError(
                "abandonment_release", f"release {tag} is no longer a draft"
            )
        return payload

    def _manifest(
        self,
        release: Mapping[str, Any],
        candidate_id: str,
        generation: int,
        version: str,
        tag: str,
        sha: str,
    ) -> dict[str, Any]:
        assets = [
            item
            for item in release.get("assets", [])
            if isinstance(item, dict) and item.get("name") == "candidate-manifest.json"
        ]
        if len(assets) != 1:
            raise ActionExecutionError(
                "abandonment_manifest",
                f"release {tag} must have one sealed manifest asset",
            )
        try:
            manifest = self.github.asset_json(
                _positive_int(assets[0].get("id"), "manifest asset id"),
                source=f"release {tag} candidate manifest",
            )
        except Exception as exc:
            raise ActionExecutionError(
                "abandonment_manifest", f"cannot read sealed manifest for {tag}: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise ActionExecutionError(
                "abandonment_manifest", "sealed manifest is malformed"
            )
        identity = (
            manifest.get("candidate_id"),
            manifest.get("generation"),
            manifest.get("version"),
            manifest.get("tag"),
            manifest.get("sha"),
        )
        expected = (candidate_id, generation, version, tag, sha)
        if identity != expected:
            raise ActionExecutionError(
                "abandonment_manifest",
                "sealed manifest identity changed before abandonment",
            )
        return manifest

    def _require_zero_public_files(self, version: str) -> None:
        try:
            inventory = self.pypi.project("sase")
        except Exception as exc:
            raise ActionExecutionError(
                "abandonment_pypi",
                f"cannot re-read the complete sase PyPI inventory: {exc}",
            ) from exc
        if not isinstance(inventory, dict) or not isinstance(
            inventory.get("releases"), dict
        ):
            raise ActionExecutionError(
                "abandonment_pypi", "sase PyPI inventory is malformed"
            )
        files = inventory["releases"].get(version, [])
        if not isinstance(files, list):
            raise ActionExecutionError(
                "abandonment_pypi", f"sase PyPI files for {version} are malformed"
            )
        if files:
            raise ActionExecutionError(
                "abandonment_pypi",
                f"candidate {version} now has public PyPI files; abandonment is refused",
                remedy="preserve the public candidate and reconcile its publication state",
            )

    def _prefix_abandoned_title(self, tag: str) -> bool:
        release = self._release_for_tag(tag)
        title = release["name"]
        if title.startswith(ABANDONED_TITLE_PREFIX):
            return False
        self._run(
            [
                "gh",
                "release",
                "edit",
                tag,
                "--title",
                f"{ABANDONED_TITLE_PREFIX}{title}",
            ],
            repo=self.repo,
        )
        return True

    def _repair_abandonment_title(
        self, request: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        snapshot = request.get("snapshot")
        trains_fact = snapshot.get("trains") if isinstance(snapshot, dict) else None
        trains = trains_fact.get("value") if isinstance(trains_fact, dict) else None
        if not isinstance(trains, list):
            return None
        for train in sorted(
            (
                item
                for item in trains
                if isinstance(item, dict) and item.get("abandoned")
            ),
            key=lambda item: (str(item.get("version", "")), str(item.get("tag", ""))),
        ):
            version = _text(train.get("version"), "train.version")
            tag = _text(train.get("tag"), "train.tag")
            candidate_id = _text(train.get("candidate_id"), "train.candidate_id")
            generation = _positive_int(train.get("generation"), "train.generation")
            self._require_zero_public_files(version)
            release = self._release_for_tag(tag)
            if release["name"].startswith(ABANDONED_TITLE_PREFIX):
                continue
            matching = [
                item
                for item in release["assets"]
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and re.fullmatch(
                    rf"candidate-gen{generation}-abandoned-run\d+-attempt\d+\.json",
                    item["name"],
                )
            ]
            if not matching:
                continue
            verified = False
            for asset in matching:
                try:
                    observation = self.github.asset_json(
                        _positive_int(asset.get("id"), "abandoned asset id"),
                        source=f"release {tag} abandoned observation",
                    )
                except Exception as exc:
                    raise ActionExecutionError(
                        "abandonment_recovery",
                        f"cannot verify the existing abandonment observation: {exc}",
                    ) from exc
                if (
                    isinstance(observation, dict)
                    and observation.get("candidate_id") == candidate_id
                    and observation.get("generation") == generation
                ):
                    verified = True
                    break
            if not verified:
                raise ActionExecutionError(
                    "abandonment_recovery",
                    f"release {tag} has no valid abandonment observation for {candidate_id}",
                )
            self._prefix_abandoned_title(tag)
            return {
                "action": {
                    "kind": "abandon_candidate",
                    "candidate_id": candidate_id,
                    "generation": generation,
                    "observation_asset": f"{candidate_id}.gen{generation}.abandoned.json",
                },
                "disposition": "executed",
                "key": f"abandon:candidate={candidate_id}:gen={generation}:asset={candidate_id}.gen{generation}.abandoned.json",
                "preconditions": [
                    "zero PyPI files",
                    "matching abandoned observation exists",
                ],
                "argv": [],
                "reason": "completed the title prefix for a previously abandoned candidate",
            }
        return None


def _train_for(
    request: Mapping[str, Any], candidate_id: str, generation: int
) -> dict[str, Any]:
    snapshot = request.get("snapshot")
    trains_fact = snapshot.get("trains") if isinstance(snapshot, dict) else None
    trains = trains_fact.get("value") if isinstance(trains_fact, dict) else None
    if isinstance(trains, list):
        for train in trains:
            if (
                isinstance(train, dict)
                and train.get("candidate_id") == candidate_id
                and train.get("generation") == generation
            ):
                return train
    raise ActionExecutionError(
        "abandonment",
        f"fresh snapshot has no matching candidate {candidate_id} generation {generation}",
    )


def _has_abandoned_train(request: Mapping[str, Any]) -> bool:
    snapshot = request.get("snapshot")
    trains_fact = snapshot.get("trains") if isinstance(snapshot, dict) else None
    trains = trains_fact.get("value") if isinstance(trains_fact, dict) else None
    return isinstance(trains, list) and any(
        isinstance(train, dict) and train.get("abandoned") is True for train in trains
    )


def _find_asset(release: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    assets = [
        item
        for item in release.get("assets", [])
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(assets) > 1:
        raise ActionExecutionError(
            "abandonment_release", f"release has duplicate asset name {name}"
        )
    return assets[0] if assets else None


def _valid_abandonment_observation(
    value: object,
    candidate_id: str,
    generation: int,
    run_id: int,
    attempt: int,
) -> bool:
    expected = {
        "kind": "abandoned",
        "candidate_id": candidate_id,
        "generation": generation,
        "run_id": run_id,
        "attempt": attempt,
        "asset": f"candidate-gen{generation}-abandoned-run{run_id}-attempt{attempt}.json",
    }
    return isinstance(value, dict) and all(
        value.get(k) == v for k, v in expected.items()
    )


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ActionExecutionError(name, f"{name} must be a positive integer")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionExecutionError(name, f"{name} must be a non-empty string")
    return value


def _set_disposition(action: dict[str, Any], disposition: str, reason: str) -> None:
    action["disposition"] = disposition
    if reason:
        action["reason"] = reason


def _append_detail(current: object, detail: str) -> str:
    prefix = current if isinstance(current, str) and current else ""
    return f"{prefix}; {detail}" if prefix else detail


def _watcher_broken(
    result: dict[str, Any], exc: ActionExecutionError
) -> dict[str, Any]:
    for field in ("train_action", "escalation"):
        action = result.get(field)
        if isinstance(action, dict) and action.get("disposition") == "proposed":
            _set_disposition(
                action,
                "suppressed",
                "mutation was not retried; re-read remote facts before another attempt",
            )
    result["primary"] = {
        "kind": "watcher_broken",
        "source": exc.source,
        "remedy": exc.remedy,
    }
    qualifier = "uncertain acknowledgement" if exc.uncertain else "execution failed"
    result["details"] = f"{qualifier}: {exc}"
    result["process_exit"] = 1
    return result


__all__ = [
    "ABANDONED_TITLE_PREFIX",
    "ActionExecutionError",
    "ReleaseWatchActionExecutor",
]
