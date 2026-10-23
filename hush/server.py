"""Webhook server: point a Grafana contact point at POST /webhook and Hush does the rest."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from fastapi import FastAPI, Request

from .decider_policy import AlertGate, DeciderUnavailable

app = FastAPI(title="hush")
gate = AlertGate()
stats = {"alerts": 0, "drop": 0, "review": 0, "page": 0, "decider_ms": 0.0, "llm_ms": 0.0, "llm_calls": 0}


def say(line: str) -> None:
    print(line, flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"decider": gate.health(), "stats": stats}


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    title = payload.get("title") or payload.get("commonLabels", {}).get("alertname", "alert")
    verdict = gate.decide(payload)
    stats["alerts"] += 1
    stats[verdict.action] += 1
    stats["decider_ms"] += verdict.latency_ms
    say(f"\n▶ {title}")
    say(f"  decider  {verdict.summary()}")
    out: dict[str, Any] = {"action": verdict.action, "reason": verdict.reason, "decider_ms": round(verdict.latency_ms)}
    if verdict.action == "drop":
        say("  → dropped, no LLM call, nobody woken")
        return out
    from .agent import handle  # imported late so the gate-only path needs no AWS

    res = handle(payload, verdict, gate)
    stats["llm_ms"] += res["llm_ms"]
    stats["llm_calls"] += 1
    say(f"  bedrock  {res['llm_ms']}ms in={res['input_tokens']} out={res['output_tokens']}")
    for g in res["guard"]:
        say(f"  guard    faithful={g['faithful']:.2f} warranted={g['warranted']:.2f} → {g['action']} ({g['ms']}ms)")
    say(f"  → {verdict.action}: {res['brief']}")
    out.update(res)
    return out


def main() -> None:
    import uvicorn

    try:
        h = gate.health()
        say(f"hush: decider {h.get('checkpoint')} on {h.get('device')} at {gate.url}")
    except DeciderUnavailable as exc:
        say(str(exc))
        sys.exit(1)
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")


if __name__ == "__main__":
    main()
