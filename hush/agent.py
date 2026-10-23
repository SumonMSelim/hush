"""The generative half: a Strands agent on Amazon Bedrock that acts on alerts the gate let through.

Two tools, one intervention. The agent writes a short brief and either pages the on-call
engineer (ntfy push) or files a note for the morning. Before `page_oncall` runs, the same
local decider checks the proposed page against the alert: is the message faithful, and is
a page warranted? Plain Python turns those two numbers into Proceed, Guide or Deny.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from strands import Agent, tool
from strands.interventions import Deny, Guide, InterventionHandler, Proceed
from strands.models import BedrockModel

from .decider_policy import AlertGate, Verdict, render_state

MODEL_ID = os.environ.get("HUSH_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
NTFY_TOPIC = os.environ.get("HUSH_NTFY_TOPIC", "")
NOTES = Path(os.environ.get("HUSH_NOTES", "morning-notes.md"))

SYSTEM_PROMPT = """You are Hush, the on-call gatekeeper for a small self-hosted server fleet.
A local decision model has already classified the alert; its verdict is given to you.
Your job: write a brief of at most three short sentences a sleepy engineer can act on:
what is broken, who is affected, the first thing to check.
If the verdict is "page", call page_oncall once with that brief. Never invent facts that are
not in the alert. If the verdict is "review", call file_morning_note once instead.
After the tool call, reply with the brief only."""


@tool
def page_oncall(title: str, message: str, priority: str = "high") -> str:
    """Wake the on-call engineer with a push notification.

    Args:
        title: short title, under 60 characters
        message: the brief, at most three sentences
        priority: "high" or "urgent"
    """
    if not NTFY_TOPIC:
        return f"[dry-run] would page: {title} / {message}"
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": "rotating_light"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return f"paged ({resp.status})"


@tool
def file_morning_note(title: str, note: str) -> str:
    """File a note for the morning review instead of paging anyone.

    Args:
        title: short title
        note: the brief
    """
    with NOTES.open("a") as f:
        f.write(f"- **{title}**: {note}\n")
    return f"filed to {NOTES}"


PAGE_QUESTIONS = {
    "faithful": {
        "type": "noul",
        "instructions": "Does the proposed page message only state facts found in the alert?",
        "criteria": {
            "true": "every claim in the message traces back to the alert text",
            "false": "the message adds a cause, a number or a host the alert never mentioned",
        },
    },
    "warranted": {
        "type": "noul",
        "instructions": "Does this alert justify waking a human right now?",
        "criteria": {
            "true": "users or data are affected now and a human must act",
            "false": "resolved, informational, cosmetic, or safely waits until morning",
        },
    },
}
YES = 0.5


class PageGuard(InterventionHandler):
    """Second use of the decider: a guardrail on the one tool that wakes a human."""

    name = "hush-page-guard"

    def __init__(self, gate: AlertGate) -> None:
        self.gate = gate
        self.alert_state = ""
        self.log: list[dict[str, Any]] = []
        self.guides = 0

    def before_tool_call(self, event, **kwargs):
        if event.tool_use["name"] != "page_oncall":
            return Proceed()
        args = event.tool_use.get("input") or {}
        state = f"{self.alert_state}\n\n--- PROPOSED PAGE ---\n{args.get('title', '')}\n{args.get('message', '')}"
        answers, ms = self.gate.ask(state, PAGE_QUESTIONS)
        faithful, warranted = answers["faithful"]["noul"], answers["warranted"]["noul"]
        row = {"faithful": round(faithful, 2), "warranted": round(warranted, 2), "ms": round(ms)}
        if warranted < YES:
            action, row["action"] = Deny(reason="The decider does not consider a page warranted; file a morning note instead."), "deny"
        elif faithful < YES and self.guides < 2:
            self.guides += 1
            action, row["action"] = Guide(feedback="The message states things the alert does not say. Rewrite it using only facts from the alert."), "guide"
        else:
            action, row["action"] = Proceed(), "proceed"
        self.log.append(row)
        return action


def build_agent(gate: AlertGate) -> tuple[Agent, PageGuard]:
    guard = PageGuard(gate)
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2),
        tools=[page_oncall, file_morning_note],
        interventions=[guard],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    return agent, guard


def handle(payload: dict[str, Any], verdict: Verdict, gate: AlertGate) -> dict[str, Any]:
    """Run the agent on one alert the gate let through. Returns the brief and the numbers."""
    agent, guard = build_agent(gate)
    guard.alert_state = render_state(payload)
    prompt = (
        f"{guard.alert_state}\n\n--- DECIDER VERDICT ---\n"
        f"action: {verdict.action}\nkind: {verdict.kind}\nwake probability: {verdict.wake:.2f}\n\n"
        "Write the brief and call the matching tool."
    )
    t0 = time.perf_counter()
    result = agent(prompt)
    ms = (time.perf_counter() - t0) * 1000
    usage = result.metrics.accumulated_usage
    return {
        "brief": str(result).strip(),
        "llm_ms": round(ms),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "guard": guard.log,
    }
