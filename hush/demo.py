"""A short, curated replay for the demo video: seven alerts through the running server.

    python -m hush.demo     # server must be running (python -m hush.server), its log shows the detail
"""

from __future__ import annotations

import json
import time
import urllib.request

from .replay import FIXTURES

PICK = [
    ("Backup finished", "firing"),
    ("Web service down", "resolved"),
    ("Root filesystem nearly full", "firing"),
    ("PostgreSQL down", "firing"),
    ("Test alert", "firing"),
    ("Tailscale node offline", "firing"),
    ("Vault sealed", "firing"),
]


def main() -> None:
    alerts = json.loads(FIXTURES.read_text())
    chosen = []
    for name, status in PICK:
        chosen.append(next(a for a in alerts if a["commonLabels"]["alertname"] == name and a["status"] == status))
    counts = {"page": 0, "review": 0, "drop": 0}
    for a in chosen:
        body = json.dumps({k: v for k, v in a.items() if k != "expect"}).encode()
        req = urllib.request.Request("http://127.0.0.1:8787/webhook", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            counts[json.loads(resp.read())["action"]] += 1
        time.sleep(2)
    time.sleep(1)
    print(f"\n{len(chosen)} alerts: {counts['page']} paged, {counts['review']} filed for the morning, "
          f"{counts['drop']} dropped with no LLM call")


if __name__ == "__main__":
    main()
