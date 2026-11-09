#!/usr/bin/env python3
"""Check behavior absent from native name-only scoring in exported sessions."""

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def tool_calls(session):
    calls = []
    for item in session.get("messages", []):
        message = (item.get("message") or {}).get("message") or {}
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call["function"]
            calls.append({"name": function["name"],
                          "arguments": json.loads(function["arguments"])})
    return calls


def name_f1(expected, actual):
    if not expected or not actual:
        return 1.0 if not expected and not actual else 0.0
    common = sum((Counter(x["name"] for x in expected) &
                  Counter(x["name"] for x in actual)).values())
    return 2 * common / (len(expected) + len(actual))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Native Docker Agent run JSON")
    parser.add_argument("--phase", required=True,
                        choices=("matrix", "baseline", "candidate", "regressed"))
    parser.add_argument("--output", type=Path, help="Write compact check results as JSON")
    args = parser.parse_args()

    fixtures = json.loads((ROOT / "cases.json").read_text())
    plans = ({case["id"]: case for case in fixtures["cases"]} if args.phase == "matrix"
             else {"comparison": fixtures["comparison"]})
    native = json.loads(args.report.read_text())
    sessions = native["sessions"]
    if {session["title"] for session in sessions} != set(plans):
        raise SystemExit("Native report cases do not match fixture cases")

    results = []
    for session in sorted(sessions, key=lambda entry: entry["title"]):
        case = plans[session["title"]]
        actual = tool_calls(session)
        planned = case["actual"] if args.phase == "matrix" else case[f"{args.phase}_actual"]
        if actual != planned:
            raise SystemExit(f"Provider trace differs from plan for {session['title']}: {actual!r}")
        expected = case["expected"]
        result = session["eval_result"]
        checks = result.get("checks") or {}
        native_tool = checks.get("tool_calls")
        predicted = name_f1(expected, actual)
        if expected:
            if native_tool is None or abs(native_tool["score"] - predicted) > 1e-9:
                raise SystemExit(f"Native name score differs from pinned formula for {session['title']}")
        elif native_tool is not None:
            raise SystemExit(f"Unexpected native tool check for empty expectation: {session['title']}")
        contract_pass = not actual if case.get("contract") == "no_tools" else actual == expected
        row = {"case": session["title"], "expected": expected, "actual": actual,
               "native_f1": native_tool["score"] if native_tool else None,
               "native_pass": result["passed"], "native_checks": checks,
               "supplemental_pass": contract_pass}
        results.append(row)
        score = "n/a" if row["native_f1"] is None else f"{row['native_f1']:.2f}"
        print(f"{row['case']:26} native={'PASS' if row['native_pass'] else 'FAIL':4} "
              f"F1={score:>4} contract={'PASS' if contract_pass else 'FAIL'}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"phase": args.phase, "native_summary": native["summary"],
                                            "cases": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
