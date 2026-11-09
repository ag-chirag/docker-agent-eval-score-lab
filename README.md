# What Docker Agent's tool-call score actually checks

This lab runs **Docker Agent v1.158.0's native `eval` command** against seven controlled conversations. A local scripted provider returns synthetic, read-only tool calls, making one property change at a time. The results show that native tool F1 compares **tool names and counts**. It does not check argument values or call order, and an empty expected-tool list does not become a no-tool prohibition. An independent trace check enforces those requirements when the application needs them.

The provider is a fixture supplied by this repository, **not** a Docker Agent feature or a real model. These runs calibrate the evaluator; they do not measure how a model behaves in production. No API key, paid model, production endpoint, or personal dataset is needed.

## What to expect

| Case | Change from the two-call positive control | Native verdict | Tool F1 | Exact trace contract |
| --- | --- | --- | ---: | --- |
| `positive` | None | PASS | 1.00 | PASS |
| `wrong_arguments` | First call uses `record-B` instead of `record-A` | PASS | 1.00 | FAIL |
| `reordered` | Same two calls, opposite order | PASS | 1.00 | FAIL |
| `repeated` | Repeats `lookup_record` | FAIL | 0.80 | FAIL |
| `unexpected` | Adds `extra_lookup` | FAIL | 0.80 | FAIL |
| `empty_expected_with_call` | No expected calls, but `extra_lookup` runs | PASS | not scored | FAIL |
| `empty_expected_no_call` | No expected or actual calls | PASS | not scored | PASS |

The native matrix reports **5/7 passing cases**, **92.0% average F1 across the five cases with nonempty expected calls**, and one passing `tool_called` assertion. The assertion is on `wrong_arguments`: it confirms `lookup_record` was present while missing its wrong argument. The separate check rejects that trace. The [annotated evidence](evidence/report.md) links each observation to the [native run JSON](evidence/native/matrix.json) and exported session calls.

## Prerequisites and pinned components

- macOS ARM64, Docker Desktop with a running Linux container engine, Python 3.9 or newer, `curl`, and `shasum`. The recorded host was macOS 15.4.1 ARM64 with Docker client/server 29.2.1; evaluation containers ran on Linux ARM64. Other hosts were not tested.
- Official [Docker Agent v1.158.0](https://github.com/docker/docker-agent/releases/tag/v1.158.0) CLI. The host binary used here reported source commit `7f94f376a5d10320591d959b351ca1eeb07c959a` and SHA-256 `0baa514a0e584c084cdf6e77cdad62e00afabf531784e6382e768c8f9ef40469` for the macOS ARM64 download. The older `cagent` executable is not interchangeable with this pinned release.
- Evaluation base image: `alpine:3.22`, resolved manifest `sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f`.
- Injected agent image: `docker/docker-agent:1.158.0`, resolved manifest `sha256:c85c9c6789be1e6aeea0252d0bfd65c960d61e81ae46e7440b47b24863eb2341`. Inside the derived eval image, `/docker-agent version` reported v1.158.0 and commit `7f94f376…`; its Linux ARM64 binary SHA-256 was `6113e636d237cffea84af183b216e3c05545e45d5ed9eb5291c485c70818acfa`. The base-image tag alone does not identify this injected binary.

The repository intentionally contains no Docker Agent binary or credentials. From a clone of this repository, install the pinned **macOS ARM64** host binary into the ignored local directory:

```sh
mkdir -p .local/bin
curl -L --fail --show-error \
  https://github.com/docker/docker-agent/releases/download/v1.158.0/docker-agent-darwin-arm64 \
  -o .local/bin/docker-agent-v1.158.0
shasum -a 256 .local/bin/docker-agent-v1.158.0
# Expected: 0baa514a0e584c084cdf6e77cdad62e00afabf531784e6382e768c8f9ef40469
chmod 755 .local/bin/docker-agent-v1.158.0
.local/bin/docker-agent-v1.158.0 version
docker version
```

Stop if the download hash or reported version differs. On another architecture, select the corresponding official release asset and record its SHA-256; the hash above applies only to `docker-agent-darwin-arm64`.

## One-command reproduction

From the repository root, after the binary check:

```sh
DOCKER_AGENT_BIN="$PWD/.local/bin/docker-agent-v1.158.0" python3 scripts/reproduce.py
```

The command generates native eval sessions from [`cases.json`](cases.json), starts a temporary local OpenAI-compatible fixture provider, verifies a Docker container can reach it, and runs the real `docker-agent eval` container path four times. It first runs the seven-case matrix, then a good baseline, a same-name wrong-argument candidate, and a genuinely regressed extra-call candidate. It runs [`check_traces.py`](scripts/check_traces.py) on each exported native session report and stops the provider even if a step fails. The fixture binds to the host loopback interface; Docker Desktop containers reach it through `host.docker.internal`. No external model request is made. The harness uses a private `--config-dir`, so it does not need the user's Docker Agent credentials.

Each run writes a new ignored `.local/runs/<UTC-time>-<pid>/` directory containing the original native JSON, command, console output, exit code, provider event log, and independent checks. The script expects native CLI exit **0** for the matrix, baseline, and wrong-argument comparison, and **1** for the deliberate regression. A failing individual evaluation does not, by itself, make the matrix CLI exit nonzero in this release. The recorded commands, consoles, reports, and trace checks are preserved under [`evidence/`](evidence/report.md).

For a single native invocation after `scripts/prepare_cases.py` has generated the sessions and the fixture server is running, the matrix command is equivalent to:

```sh
FIXTURE_BASE_URL=http://host.docker.internal:8765/matrix/v1 \
  .local/bin/docker-agent-v1.158.0 eval agent.yaml .local/evals-matrix \
  --base-image alpine@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f \
  --agent-image docker/docker-agent@sha256:c85c9c6789be1e6aeea0252d0bfd65c960d61e81ae46e7440b47b24863eb2341 \
  --concurrency 1 -e FIXTURE_BASE_URL
```

`reproduce.py` supplies the current ephemeral fixture port and uses the same pinned image digests. It creates no persistent service or deployed agent.

## How the score and gate behave

The [pinned scoring source](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/scoring.go) counts matching names as a multiset. For expected `[lookup_record, read_policy]` and actual `[lookup_record, read_policy, extra_lookup]`, two names match, so precision is `2/3`, recall is `2/2`, and F1 is `0.80`. Reordering the two calls or changing `record_id` leaves the name multiset unchanged, so F1 stays `1.00`.

The [evaluation path](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/eval.go) extracts expected names from the recorded session and actual names from container events. The [verdict logic](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/types.go) checks tool F1 only when at least one expected call exists. Thus `empty_expected_with_call` receives no native tool check and passes when no other criterion fails. Its explicit independent `no_tools` contract fails. `tool_called` is a useful built-in **presence** assertion, but it does not validate arguments, order, or absence of other calls.

The baseline comparison makes the release-gate implication concrete. The good baseline scores 1.00. A candidate changing only `record_id` also scores 1.00, reports **No regression against baseline**, and exits 0, although the exact trace check fails. A candidate adding `extra_lookup` scores 0.80, reports a pass-to-fail change and **Regression against baseline**, and exits 1. The printed `failure rate` stays 0 because that aggregate tracks execution errors, not all quality failures; inspect the per-case verdict and changed-evaluation section as well.

## Project layout

- [`agent.yaml`](agent.yaml) defines three synthetic, read-only script tools and a custom Chat Completions endpoint. Their commands only print fixture identifiers.
- [`cases.json`](cases.json) is the reviewable expected/actual call matrix and comparison plan.
- [`scripts/fixture_provider.py`](scripts/fixture_provider.py) returns one planned tool call per turn over a local OpenAI-compatible API. It is test infrastructure, not a Docker-shipped provider.
- [`scripts/prepare_cases.py`](scripts/prepare_cases.py) creates native recorded-session JSON in the ignored local directory.
- [`scripts/check_traces.py`](scripts/check_traces.py) reads Docker Agent's exported sessions and checks exact names, argument objects, order, and no-tool requirements. It also cross-checks the native name F1 against the pinned formula, but never substitutes for `docker-agent eval`.
- [`scripts/reproduce.py`](scripts/reproduce.py) drives the bounded runs and records exit codes and outputs.

## Limits and cleanup

This is an evaluator calibration with a deterministic provider. It demonstrates properties of v1.158.0 on the tested local Docker Desktop setup, not that any real model will make these calls, nor that all future releases score identically. No relevance judge, response-size criterion, or paid provider was used. The lone `tool_called` assertion is deliberate and documented. The reported model cost is `$0.000000` because the scripted provider has no paid model; image downloads still require network access and disk space. The native evaluator launches isolated **privileged** containers in this release, so use only disposable synthetic fixtures and a trusted local Docker engine.

The provider stops automatically. Native eval containers run with `--rm`. Remove only the generated local run data when you no longer need it:

```sh
rm -rf .local/runs .local/evals-matrix .local/evals-comparison .local/bin
```

The command does not remove your other Docker images, containers, or personal Docker Agent configuration. To reclaim just the two downloaded source images later, inspect `docker image ls` and remove them explicitly if nothing else uses them. The checked-in evidence remains available after `.local/` cleanup.
