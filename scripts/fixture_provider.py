#!/usr/bin/env python3
"""Deterministic OpenAI Chat Completions fixture for native Docker Agent evals.

This is a local test provider, not a Docker Agent feature or a model. It emits
one synthetic tool call per turn so exported traces preserve call order.
"""

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_PATTERN = re.compile(r"CASE_ID=([a-z_]+)")


def load_plans():
    data = json.loads((ROOT / "cases.json").read_text())
    return {case["id"]: case for case in data["cases"]}, data["comparison"]


class Handler(BaseHTTPRequestHandler):
    server_version = "DockerAgentEvalFixture/1"

    def log_message(self, format, *args):
        # Keep request bodies and host addresses out of the portable evidence.
        pass

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self._json(200, {"status": "ok"})

    def do_POST(self):
        match = re.fullmatch(r"/(matrix|baseline|candidate|regressed)/v1/chat/completions", self.path)
        if not match:
            self._json(404, {"error": "unknown endpoint"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(length))
            messages = request["messages"]
            user_text = next(
                message["content"]
                for message in messages
                if message.get("role") == "user" and isinstance(message.get("content"), str)
            )
            case_id = CASE_PATTERN.search(user_text).group(1)
            phase = match.group(1)
            cases, comparison = self.server.plans
            if case_id == "comparison":
                plan = comparison[f"{phase}_actual"]
            else:
                plan = cases[case_id]["actual"]
            completed = sum(message.get("role") == "tool" for message in messages)
            call = plan[completed] if completed < len(plan) else None
        except (KeyError, TypeError, ValueError, StopIteration, AttributeError, IndexError) as error:
            self._json(400, {"error": f"invalid fixture request: {type(error).__name__}"})
            return

        with self.server.log_path.open("a") as log:
            log.write(json.dumps({"phase": phase, "case": case_id, "completed_tools": completed,
                                  "emitted_tool": call["name"] if call else None}) + "\n")

        if not request.get("stream", False):
            message = self._message(call, case_id, completed)
            self._json(200, {"id": "fixture", "object": "chat.completion", "created": int(time.time()),
                             "model": "fixture-chat", "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if call else "stop"}]})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        delta = self._message(call, case_id, completed)
        self._event({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        self._event({"choices": [{"index": 0, "delta": {},
                                  "finish_reason": "tool_calls" if call else "stop"}]})
        self._event({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                             "total_tokens": 15}})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _message(self, call, case_id, completed):
        if call is None:
            return {"role": "assistant", "content": f"Synthetic case {case_id} completed."}
        return {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{case_id}_{completed}",
                 "type": "function", "function": {"name": call["name"],
                 "arguments": json.dumps(call["arguments"], separators=(",", ":"))}}]}

    def _event(self, fields):
        chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": int(time.time()),
                 "model": "fixture-chat", **fields}
        self.wfile.write(b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n")
        self.wfile.flush()

    def _json(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=ROOT / ".local" / "provider-events.jsonl")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.plans = load_plans()
    server.log_path = args.log
    print(f"Fixture provider ready on port {server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
