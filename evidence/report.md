# Native evaluation evidence

This record comes from a complete one-command run on November 9, 2026. The [original native run JSON](native/matrix.json) contains every case's `sessions[].eval_result`, expected criteria, and exported conversation. The [exact invocation flags and recorded exit codes](commands.txt), [console text](console.txt), [provider emissions](provider-events.jsonl), and [independent trace results](checks.json) are preserved separately. The [matrix console image](matrix-console.png) and [baseline console image](baseline-console.png) are legible renders of those recorded console logs, **not** direct desktop screenshots or fabricated model output. The image rendering normalizes some unsupported terminal symbols; the original text is authoritative.

## Runtime and provenance

| Component | Recorded value |
| --- | --- |
| Host | macOS 15.4.1, ARM64 |
| Docker client/server | 29.2.1 / 29.2.1; Linux ARM64 containers |
| Host Docker Agent CLI | v1.158.0, source commit `7f94f376a5d10320591d959b351ca1eeb07c959a`, macOS ARM64 SHA-256 `0baa514a0e584c084cdf6e77cdad62e00afabf531784e6382e768c8f9ef40469` |
| Evaluation base | `alpine:3.22` at `sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f` |
| Injected agent image | `docker/docker-agent:1.158.0` at `sha256:c85c9c6789be1e6aeea0252d0bfd65c960d61e81ae46e7440b47b24863eb2341` |
| Derived image checked | `sha256:14f2442899cc76eefb3fd5fff6ae851ae7dfbe41605bd33e67c1cd4a70585475`; `/docker-agent version` was v1.158.0 at commit `7f94f376…`; Linux ARM64 binary SHA-256 `6113e636d237cffea84af183b216e3c05545e45d5ed9eb5291c485c70818acfa` |
| Provider | Repository-local deterministic Chat Completions fixture over `host.docker.internal`; no model credentials or external model calls |

The actual CLI used `--base-image alpine@sha256:49340b…`, `--agent-image docker/docker-agent@sha256:c85c9…`, `--concurrency 1`, and `-e FIXTURE_BASE_URL`. `reproduce.py` supplied an ephemeral local port, used isolated data/config directories, and verified container-to-provider reachability before evaluation. The custom fixture drives the **real** Docker Agent evaluation containers. It is not a replacement scoring engine and is not a Docker-shipped provider. All tool commands only print synthetic identifiers.

## Controlled matrix

The expected sequence for cases with nonempty expectations is `lookup_record({"record_id":"record-A"})`, then `read_policy({"policy_id":"policy-P"})`. The supplementary contract compares the exported argument objects **in order**. For empty expectations, the independent `no_tools` contract requires zero calls. Every listed actual call was recovered from the native exported session and matched the provider plan; no evaluation had a runtime error.

| Case | Actual call difference | Native per-case verdict | Native tool F1 | Independent contract |
| --- | --- | --- | ---: | --- |
| `positive` | None | PASS | 1.00 | PASS |
| `wrong_arguments` | `lookup_record` uses `record-B`; `tool_called(lookup_record)` assertion also passes 1/1 | PASS | 1.00 | FAIL |
| `reordered` | `read_policy` precedes `lookup_record` | PASS | 1.00 | FAIL |
| `repeated` | Third call repeats `lookup_record` | FAIL | 0.80 | FAIL |
| `unexpected` | Third call is `extra_lookup({"item_id":"item-X"})` | FAIL | 0.80 | FAIL |
| `empty_expected_with_call` | `extra_lookup` despite no expected calls | PASS; no native tool check | n/a | FAIL |
| `empty_expected_no_call` | No calls | PASS; no native tool check | n/a | PASS |

The matrix's native summary has `total_evals=7`, `failed_evals=0` (no **execution errors**), `tools_f1_sum=4.6`, `tools_count=5`, and `assertions_passed=1/1`. The console shows five passing and two failing **quality verdicts**, average tool F1 **92.0%**, cost `$0.000000`, and CLI exit **0**. Thus a matrix with failing individual cases still returned zero from this invocation. No relevance or size criteria were configured, and no judge ran. The sole `tool_called` assertion deliberately tests presence only.

The name F1 calculation in [Docker Agent v1.158.0's scoring source](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/scoring.go) uses a multiset intersection. With two expected names and three actual names, `TP=2`, precision `2/3`, recall `2/2`, so F1 `0.80`. A change to arguments or order preserves the multiset and gets F1 `1.00`. The [evaluation path](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/eval.go) sets `ToolCallsExpected` only when expected calls are nonempty; [verdict and summary logic](https://github.com/docker/docker-agent/blob/v1.158.0/pkg/evaluation/types.go) then omit the tool check/count for an empty expected list. The observed `empty_expected_with_call` result has no `checks.tool_calls` entry. An explicit no-tool rule therefore belongs in an independent trace contract.

## Baseline comparison and exit status

The same `comparison` eval session ID/title and expected calls were used in all three runs. Only the fixture provider phase changed; the recorded expected sequence did not. The good [baseline report](native/baseline.json) has F1 1.00 and CLI exit 0. The [candidate report](native/candidate.json) changes `record-A` to `record-B` but keeps tool names, F1 1.00, native PASS, independent contract FAIL. The native `--baseline` output says **No regression against baseline** and exits **0**. The [regressed report](native/regressed.json) adds `extra_lookup`, F1 0.80, native FAIL, independent contract FAIL; `--baseline` reports a pass-to-fail change, **Regression against baseline**, and exits **1**.

The exact commands were generated by [`scripts/reproduce.py`](../scripts/reproduce.py), which invokes the pinned CLI with the same agent/eval session files and different `FIXTURE_BASE_URL` phase paths. The `--baseline` argument for both candidate invocations was the saved baseline native JSON. [Recorded commands](commands.txt) preserve the actual phase ports and flags while normalizing only the host binary's private path to the README installation path. The exact console outputs and captured exit codes are in [console.txt](console.txt). The printed baseline `failure rate` remained 0 even for the regressed quality case because this aggregate tracks evaluation **errors**, while the changed-evaluation section records the pass-to-fail quality transition. Do not use that aggregate alone as the release decision.

## What was and was not tested

- **PASS:** Real v1.158.0 `docker-agent eval` built and ran isolated containers for all seven matrix cases and three comparison phases. The fixture provider emitted planned tool calls, and exported sessions retained names, argument JSON, and order.
- **PASS:** Independent trace checks accepted the positive and no-call controls and rejected wrong arguments, wrong order, repeated/unexpected calls, and the known bad no-tool case. They also checked native F1 values against the pinned source formula.
- **PASS:** Native baseline comparison accepted the wrong-argument candidate with exit 0 and rejected the extra-call regression with exit 1; this demonstrates the gate's measured boundary.
- **Limit:** No real model behavior, relevance judge, cloud runtime, other host architecture, or production release pipeline was evaluated. A deterministic fixture calibrates the evaluator; a separate real-model run would be needed to assess an agent's actual reliability and cost.

## Release checklist for a real agent

1. Pin and record the host CLI, base image **and injected binary**. Inspect the derived image rather than inferring the agent version from its base tag.
2. Open the exported session trace and the per-case verdict. Compare names, arguments, order, repeat counts, and forbidden actions against the application's actual requirements.
3. Add independent deterministic checks for properties the built-in name F1 and `tool_called` presence assertion do not express. Include both a passing control and a known failing control.
4. Run a baseline comparison and record its output and exit code. Verify that the chosen criteria can cause a meaningful regression before making it a gate.
5. Keep scripted evaluator calibration separate from real-model evaluations; use representative model runs and their actual costs before approving a prompt or routing change.
