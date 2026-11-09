#!/usr/bin/env python3
"""Run the bounded native evaluation matrix and baseline comparisons."""

import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "alpine@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"
AGENT_IMAGE = "docker/docker-agent@sha256:c85c9c6789be1e6aeea0252d0bfd65c960d61e81ae46e7440b47b24863eb2341"


def command(args, *, env=None, output=None):
    completed = subprocess.run(args, cwd=ROOT, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               check=False)
    if output:
        output.write_text(completed.stdout)
    return completed


def run_eval(cli, run_dir, phase, eval_dir, provider_port, baseline=None):
    output_dir = run_dir / phase
    output_dir.mkdir()
    args = [str(cli), "--config-dir", str(run_dir / "config"),
            "--data-dir", str(run_dir / "data"), "--cache-dir", str(run_dir / "cache"),
            "eval", "agent.yaml", str(eval_dir), "--base-image", BASE_IMAGE,
            "--agent-image", AGENT_IMAGE, "--concurrency", "1", "--output",
            str(output_dir), "-e", "FIXTURE_BASE_URL"]
    if baseline:
        args += ["--baseline", str(baseline)]
    env = os.environ.copy()
    env.update({"TELEMETRY_ENABLED": "false",
                "FIXTURE_BASE_URL": f"http://host.docker.internal:{provider_port}/{phase}/v1"})
    (run_dir / f"{phase}.command.txt").write_text(
        "TELEMETRY_ENABLED=false FIXTURE_BASE_URL="
        + shlex.quote(env["FIXTURE_BASE_URL"]) + " " + shlex.join(args) + "\n")
    result = command(args, env=env, output=run_dir / f"{phase}.console.txt")
    (run_dir / f"{phase}.exit.txt").write_text(f"{result.returncode}\n")
    expected_exit = 1 if phase == "regressed" else 0
    if result.returncode != expected_exit:
        raise RuntimeError(f"{phase}: CLI exit {result.returncode}, expected {expected_exit}; "
                           f"see {run_dir / (phase + '.console.txt')}")
    if phase == "candidate" and "No regression against baseline" not in result.stdout:
        raise RuntimeError("Candidate run did not report the expected native no-regression verdict")
    if phase == "regressed" and "❌ Regression against baseline" not in result.stdout:
        raise RuntimeError("Regressed run did not report the expected native gate failure")
    reports = list(output_dir.glob("*.json"))
    if len(reports) != 1:
        raise RuntimeError(f"{phase}: expected one native run JSON, found {len(reports)}")
    checks = command([sys.executable, "scripts/check_traces.py", str(reports[0]),
                      "--phase", phase, "--output", str(run_dir / f"{phase}.checks.json")])
    (run_dir / f"{phase}.checks.txt").write_text(checks.stdout)
    if checks.returncode:
        raise RuntimeError(f"{phase}: trace checks failed: {checks.stdout}")
    rows = json.loads((run_dir / f"{phase}.checks.json").read_text())["cases"]
    expected = {
        "matrix": {
            "positive": (True, True, 1.0),
            "wrong_arguments": (True, False, 1.0),
            "reordered": (True, False, 1.0),
            "repeated": (False, False, 0.8),
            "unexpected": (False, False, 0.8),
            "empty_expected_with_call": (True, False, None),
            "empty_expected_no_call": (True, True, None),
        },
        "baseline": {"comparison": (True, True, 1.0)},
        "candidate": {"comparison": (True, False, 1.0)},
        "regressed": {"comparison": (False, False, 0.8)},
    }[phase]
    observed = {row["case"]: (row["native_pass"], row["supplemental_pass"],
                              row["native_f1"]) for row in rows}
    if observed != expected:
        raise RuntimeError(f"{phase}: verdicts drifted from pinned release: {observed!r}")
    print(f"{phase}: native CLI exit {result.returncode}; trace checks matched fixture plan")
    print(checks.stdout, end="")
    return reports[0]


def main():
    os.chdir(ROOT)
    cli_name = os.environ.get("DOCKER_AGENT_BIN", "docker-agent")
    cli_resolved = shutil.which(cli_name)
    if not cli_resolved:
        raise SystemExit("Set DOCKER_AGENT_BIN to the official Docker Agent v1.158.0 binary")
    cli = Path(cli_resolved).resolve()
    version = command([str(cli), "version"])
    if version.returncode or "docker-agent version v1.158.0" not in version.stdout:
        raise SystemExit(f"Expected Docker Agent v1.158.0, got: {version.stdout.strip()}")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(".local") / "runs" / f"{stamp}-{os.getpid()}"
    (ROOT / run_dir).mkdir(parents=True)
    prepared = command([sys.executable, "scripts/prepare_cases.py"])
    if prepared.returncode:
        raise RuntimeError(prepared.stdout)

    provider_err = (ROOT / run_dir / "provider.stderr.txt").open("w")
    provider = subprocess.Popen([sys.executable, "-u", "scripts/fixture_provider.py",
                                 "--bind", "127.0.0.1", "--port", "0", "--log",
                                 str(run_dir / "provider-events.jsonl")],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=provider_err,
                                text=True)
    try:
        ready = provider.stdout.readline().strip()
        if not ready.startswith("Fixture provider ready on port "):
            raise RuntimeError(f"Fixture provider did not start: {ready!r}")
        port = int(ready.rsplit(" ", 1)[-1])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("Fixture health check failed")
        reachability = command(["docker", "run", "--rm", BASE_IMAGE, "wget", "-qO-",
                                f"http://host.docker.internal:{port}/health"])
        if reachability.returncode or '"status": "ok"' not in reachability.stdout:
            raise RuntimeError(f"Evaluation container cannot reach fixture: {reachability.stdout}")
        print(f"Container-to-fixture health check passed (port {port})")

        matrix_dir = Path(".local/evals-matrix")
        comparison_dir = Path(".local/evals-comparison")
        run_eval(cli, run_dir, "matrix", matrix_dir, port)
        baseline_report = run_eval(cli, run_dir, "baseline", comparison_dir, port)
        run_eval(cli, run_dir, "candidate", comparison_dir, port, baseline_report)
        run_eval(cli, run_dir, "regressed", comparison_dir, port, baseline_report)
        print(f"Native reports and trace checks: {run_dir}")
    finally:
        provider.terminate()
        try:
            provider.wait(timeout=5)
        except subprocess.TimeoutExpired:
            provider.kill()
            provider.wait()
        provider_err.close()


if __name__ == "__main__":
    main()
