"""Replay the fixture alerts.

    python -m hush.replay            # gate only: decider verdicts, accuracy against `expect`, latency
    python -m hush.replay --serve    # POST each alert to the running hush server (the full show)
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

from .decider_policy import AlertGate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "alerts.json"


def gate_only(alerts: list[dict]) -> None:
    gate = AlertGate()
    gate.decide(alerts[0])  # warm-up: the first request at a new length pays a compile
    gate.server_ms.clear()
    rows, hits, lat = [], 0, []
    for a in alerts:
        v = gate.decide(a)
        ok = v.action == a["expect"]
        hits += ok
        lat.append(v.latency_ms)
        mark = " " if ok else "✗"
        print(f"{mark} want={a['expect']:6s} got={v.summary()}  [{a['title']}]")
        rows.append({"title": a["title"], "expect": a["expect"], "got": v.action, "ms": v.latency_ms, **{k: getattr(v, k) for k in ("kind", "kind_confidence", "wake")}})
    n = len(alerts)
    silenced_pages = sum(1 for r in rows if r["expect"] == "page" and r["got"] == "drop")
    print(f"\n{hits}/{n} match the on-call engineer's verdict ({100 * hits / n:.0f}%); pages silenced: {silenced_pages}")
    print(f"decider latency: median {statistics.median(lat):.0f}ms, p90 {sorted(lat)[int(0.9 * n) - 1]:.0f}ms, "
          f"total {sum(lat) / 1000:.1f}s for {n} alerts x 2 questions, {gate.input_tokens} input tokens")
    if gate.server_ms:
        print(f"decider compute (server-side, no network): median {statistics.median(gate.server_ms):.0f}ms")
    Path("replay-results.json").write_text(json.dumps(rows, indent=1))
    sweep(rows)


def sweep(rows: list[dict]) -> None:
    """The wake probability is a dial, not a verdict. Show what each page line would do."""
    pages = [r for r in rows if r["expect"] == "page"]
    others = [r for r in rows if r["expect"] != "page"]
    print("\npage line  real pages caught  false pages")
    for t in (0.60, 0.65, 0.70, 0.75, 0.77, 0.80, 0.85, 0.90):
        caught = sum(r["wake"] >= t for r in pages)
        false = sum(r["wake"] >= t for r in others)
        print(f"  {t:.2f}        {caught:2d}/{len(pages)}              {false:2d}")


def serve(alerts: list[dict], url: str = "http://127.0.0.1:8787/webhook") -> None:
    t0 = time.perf_counter()
    for a in alerts:
        body = json.dumps({k: v for k, v in a.items() if k != "expect"}).encode()
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = json.loads(resp.read())
        print(f"{out['action']:6s} {out['decider_ms']:4d}ms  {a['title']}")
    print(f"\n{len(alerts)} alerts in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    alerts = json.loads(FIXTURES.read_text())
    if "--serve" in sys.argv:
        serve(alerts)
    else:
        gate_only(alerts)
