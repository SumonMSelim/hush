"""Reusable pattern: classify an alert with Strands Decider before an agent acts on it.

Drop this file into your own agent. It needs nothing beyond the standard library and a
running `strands-decider serve` on STRANDS_DECIDER_URL (default http://127.0.0.1:8099).

    gate = AlertGate()
    verdict = gate.decide(alert_payload)      # one round trip, no tokens billed
    if verdict.action == "page": ...           # plain Python decides, the model classifies

The recipe has three parts, and each is swappable on its own:

1. `render_state`  : the alert as plain text the decider reads once.
2. `QUESTIONS`     : two typed questions, answered together on that one state.
3. `policy`        : control flow over the answers and their confidences.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

DECIDER_URL = os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099")

# --------------------------------------------------------------------------- 1. the state


def render_state(payload: dict[str, Any]) -> str:
    """Flatten a Grafana (Alertmanager-shaped) webhook into text. Only the human-readable
    fields: labels, annotations, status. The decider reads this once for all questions."""
    lines = ["An alert from the monitoring system of a small self-hosted server fleet."]
    for a in payload.get("alerts", []):
        labels = a.get("labels", {})
        ann = a.get("annotations", {})
        lines.append("")
        lines.append(f"status: {a.get('status', payload.get('status', 'firing'))}")
        lines.append(f"alert: {labels.get('alertname', '?')}")
        lines.append(f"severity label: {labels.get('severity', 'none')}")
        extra = {k: v for k, v in labels.items() if k not in ("alertname", "severity", "grafana_folder")}
        if extra:
            lines.append("labels: " + ", ".join(f"{k}={v}" for k, v in extra.items()))
        if ann.get("summary"):
            lines.append(f"summary: {ann['summary']}")
        if ann.get("description"):
            lines.append(f"description: {ann['description']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 2. the questions
#
# Two narrow questions, one judgement each. The option descriptions carry most of the
# signal: they are where your on-call policy lives ("a laptop is never worth waking for"),
# so write them as carefully as the questions. On a CPU every question costs a forward
# pass, so ask only what the policy branches on. On a GPU extra questions are nearly free.

QUESTIONS: dict[str, dict[str, Any]] = {
    "wake": {
        "type": "noul",
        "instructions": "Should the on-call engineer be woken up at 3am for this alert?",
        "criteria": {
            "true": "it is firing now, a server or service that people or other services depend on is down, "
            "at risk of data loss, or under attack, and it will not fix itself",
            "false": "it is resolved, a test, a routine report, a flap that recovered, a laptop or phone or "
            "dev container, or a slow problem that can wait until morning",
        },
    },
    "kind": {
        "type": "choice",
        "instructions": "What kind of event is this alert reporting?",
        "criteria": {
            "outage": "a server, service or dependency that others rely on is down right now",
            "degradation": "something is slow, filling up or under pressure but still working",
            "security": "an attack, exposed secret, expiring certificate or sealed vault",
            "noise": "already resolved, a flap, a test, or a laptop, phone or throwaway dev container",
            "informational": "a routine report of normal operation, nothing is wrong",
        },
    },
}

# --------------------------------------------------------------------------- 3. the policy
#
# The thresholds are the policy's knobs, owned by the code, not the model. These were set
# by replaying 40 labelled alerts (python -m hush.replay): every real page scored wake >= 0.77
# and every alert worth a morning note scored >= 0.5. Measure them on your own traffic.

PAGE_AT = 0.77  # wake probability at or above this pages a human
DROP_BELOW = 0.5  # wake probability below this is silenced
CONFIRM = 0.5  # choice confidence needed before the `kind` answer may veto or silence
QUIET_KINDS = ("noise", "informational")


@dataclass
class Verdict:
    action: str  # page | review | drop
    reason: str
    kind: str
    kind_confidence: float
    wake: float
    latency_ms: float
    answers: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"{self.action:6s} wake={self.wake:.2f} kind={self.kind:<13s} ({self.kind_confidence:.2f}) "
            f"{self.latency_ms:5.0f}ms  {self.reason}"
        )


def policy(answers: dict[str, Any], latency_ms: float = 0.0) -> Verdict:
    """Turn typed answers into one of three actions. Ordinary control flow; the first
    matching branch wins. Anything in between goes to `review`, where the LLM writes a note
    and a human reads it in the morning: an uncertain classifier never silences an alert."""
    wake = answers["wake"]["noul"]
    kind = answers["kind"]["choice"]
    conf = answers["kind"]["confidence"]
    quiet = kind in QUIET_KINDS and conf >= CONFIRM
    v = dict(kind=kind, kind_confidence=conf, wake=wake, latency_ms=latency_ms, answers=answers)

    if wake < DROP_BELOW:
        return Verdict("drop", f"wake {wake:.2f} < {DROP_BELOW}", **v)
    if quiet and wake < PAGE_AT:
        return Verdict("drop", f"{kind} at {conf:.2f}, wake {wake:.2f}", **v)
    if wake >= PAGE_AT and not quiet:
        return Verdict("page", f"wake {wake:.2f} >= {PAGE_AT}, {kind}", **v)
    return Verdict("review", f"wake {wake:.2f}, {kind}", **v)


# --------------------------------------------------------------------------- the wiring


class DeciderUnavailable(RuntimeError):
    pass


class AlertGate:
    """One state, two questions, one round trip to a strands-decider server."""

    def __init__(self, url: str = DECIDER_URL, timeout: float = 120.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.calls = 0
        self.input_tokens = 0
        self.server_ms: list[float] = []  # compute time reported by the decider, without network

    def ask(self, state: str, questions: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
        body = json.dumps({"state": state, "model": "strands-decider", "questions": questions}).encode()
        req = urllib.request.Request(
            f"{self.url}/v1/systemone", data=body, headers={"content-type": "application/json"}
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise DeciderUnavailable(
                f"no strands-decider at {self.url} ({exc}). Start one with:\n"
                "    strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --port 8099"
            ) from exc
        ms = (time.perf_counter() - t0) * 1000
        self.calls += 1
        self.input_tokens += payload.get("usage", {}).get("input_tokens", 0)
        if payload.get("latency_ms") is not None:
            self.server_ms.append(float(payload["latency_ms"]))
        return payload["answers"], ms

    def decide(self, payload: dict[str, Any]) -> Verdict:
        answers, ms = self.ask(render_state(payload), QUESTIONS)
        return policy(answers, ms)

    def health(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise DeciderUnavailable(str(exc)) from exc
