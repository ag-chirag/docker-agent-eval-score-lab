#!/usr/bin/env python3
"""Generate native Docker Agent session fixtures from the reviewable case matrix."""

import json
import shutil
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
NAMESPACE = uuid.UUID("e45bfcc0-06af-4c37-90d0-14f14e747b6e")


def session(case):
    case_id = case["id"]
    messages = [{"message": {"agent_name": "root", "message": {
        "role": "user", "content": f"CASE_ID={case_id}. Use the synthetic read-only tools as needed."}}}]
    for index, call in enumerate(case["expected"]):
        call_id = f"expected_{case_id}_{index}"
        messages.append({"message": {"agent_name": "root", "message": {
            "role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
                "name": call["name"],
                "arguments": json.dumps(call["arguments"], separators=(",", ":"))}}]}}})
        messages.append({"message": {"agent_name": "root", "message": {
            "role": "tool", "tool_call_id": call_id, "content": "synthetic read-only result"}}})
    return {"id": str(uuid.uuid5(NAMESPACE, case_id)), "title": case_id,
            "messages": messages, "evals": {"assertions": case.get("assertions", [])}}


def write_dir(path, cases):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    for case in cases:
        (path / f"{case['id']}.json").write_text(json.dumps(session(case), indent=2) + "\n")


def main():
    data = json.loads((ROOT / "cases.json").read_text())
    write_dir(LOCAL / "evals-matrix", data["cases"])
    write_dir(LOCAL / "evals-comparison", [data["comparison"]])
    print(f"Generated {len(data['cases'])} matrix sessions and 1 comparison session")


if __name__ == "__main__":
    main()
