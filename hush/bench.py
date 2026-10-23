"""Measure the decision moved off the LLM: decider vs a Bedrock model on the same 40 alerts.

    python -m hush.bench                      # decider + Nova 2 Lite
    python -m hush.bench --model <bedrock-id> # any Bedrock model that supports Converse

Both answer the same question: page, review or drop. Reports agreement with the engineer's
verdict, median latency and tokens. Prices are not hard-coded; multiply the token counts by
the Bedrock price list for your region.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

import boto3

from .decider_policy import AlertGate, render_state
from .replay import FIXTURES

# The same on-call policy the decider's option descriptions carry, so the comparison is fair.
PROMPT = """You are the on-call gatekeeper for a small self-hosted server fleet. Classify this alert.

page: it is firing now, a server or service that people or other services depend on is down, at risk of data loss, or under attack, and it will not fix itself. Wake a human at 3am.
review: a real problem that can wait until morning: something slow, filling up or under pressure but still working.
drop: it is resolved, a test, a routine report, a flap that recovered, or a laptop, phone or dev container.

Answer with exactly one word: page, review or drop.

{state}"""


def llm_classify(client, model_id: str, state: str) -> tuple[str, float, int, int]:
    t0 = time.perf_counter()
    r = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": PROMPT.format(state=state)}]}],
        inferenceConfig={"maxTokens": 8, "temperature": 0},
    )
    ms = (time.perf_counter() - t0) * 1000
    text = r["output"]["message"]["content"][0]["text"].lower()
    word = next((w for w in re.findall(r"[a-z]+", text) if w in ("page", "review", "drop")), text.strip()[:12])
    return word, ms, r["usage"]["inputTokens"], r["usage"]["outputTokens"]


def main() -> None:
    model_id = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "us.amazon.nova-2-lite-v1:0"
    alerts = json.loads(FIXTURES.read_text())
    gate = AlertGate()
    client = boto3.client("bedrock-runtime", region_name="us-east-1")
    gate.decide(alerts[0])
    llm_classify(client, model_id, render_state(alerts[0]))  # warm both
    gate.server_ms.clear()

    d_hits = l_hits = 0
    d_ms, l_ms, l_in, l_out = [], [], 0, 0
    for a in alerts:
        v = gate.decide(a)
        word, ms, i, o = llm_classify(client, model_id, render_state(a))
        d_hits += v.action == a["expect"]
        l_hits += word == a["expect"]
        d_ms.append(v.latency_ms)
        l_ms.append(ms)
        l_in += i
        l_out += o
        print(f"want={a['expect']:6s} decider={v.action:6s} {v.latency_ms:4.0f}ms  llm={word:6s} {ms:5.0f}ms  {a['title']}")

    n = len(alerts)
    res = {
        "n": n,
        "decider": {"agreement": d_hits / n, "median_ms": statistics.median(d_ms), "median_compute_ms": statistics.median(gate.server_ms) if gate.server_ms else None, "input_tokens": gate.input_tokens, "questions_per_alert": 2},
        model_id: {"agreement": l_hits / n, "median_ms": statistics.median(l_ms), "input_tokens": l_in, "output_tokens": l_out},
    }
    print(json.dumps(res, indent=1))
    Path("bench-results.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
