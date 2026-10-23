# Hush: a decision model decides whether an alert may wake you, Bedrock writes the brief

*Agent Experience Hackathon submission. Pattern: #policy. Tags: #strands-decider-2b #policy.*

I run a small self-hosted fleet: two Proxmox nodes, a dozen LXC containers, Postgres, Immich, Jellyfin, Outline, Vault, a Caddy edge, all watched by Grafana. Grafana pushes every alert to my phone through ntfy. That means my phone buzzes at 3 am for a resolved notice, for my laptop leaving the tailnet, for a weekly docker prune report, and, now and then, for the database being actually down. After a few weeks of this you stop reading the pushes. That is how you miss the real one.

So I built Hush, an on-call gatekeeper. Grafana posts each alert to Hush. Hush decides whether anyone should be woken, and only then asks an LLM on Amazon Bedrock to write the three sentences a sleepy engineer needs.

The decision is handed to Strands Decider 2B. The writing is done by Amazon Nova 2 Lite through the Strands Agents SDK.

## Why not let the LLM decide

I tried. Two problems.

First, cost and latency. Every alert, including the forty a day that are pure noise, became a Bedrock call. That is fine for a demo and wrong for something that runs forever.

Second, and worse, an LLM asked "should I wake someone?" can be talked into either answer by the wording of the alert. A rule titled "Web service down" with severity "critical" reads as urgent even when its status is "resolved" and the description says the site is back. A chat model gives you prose you then have to parse, and the prose changes when the alert changes.

A decision model does not generate text. It reads the alert once and answers typed questions with calibrated probabilities. The thresholds live in my code, where I can test them. The model classifies, the code decides.

## The decision I handed to Decider 2B

One state, two questions, one round trip:

```python
QUESTIONS = {
    "wake": noul("Should the on-call engineer be woken up at 3am for this alert?", {
        "true":  "it is firing now, a server or service that people or other services depend on is down, "
                 "at risk of data loss, or under attack, and it will not fix itself",
        "false": "it is resolved, a test, a routine report, a flap that recovered, a laptop or phone or "
                 "dev container, or a slow problem that can wait until morning"}),
    "kind": choice("What kind of event is this alert reporting?",
                   outage | degradation | security | noise | informational),
}
```

The state is the Grafana webhook flattened to text: status, alert name, severity label, the other labels, summary and description.

The policy is a dozen lines of Python:

- **drop** when wake is below 0.5, or when the model is confident (choice confidence at least 0.5) the alert is noise or information and wake is under the page line. No LLM call, nobody woken.
- **page** when wake is at or above 0.77 and the kind is not confidently quiet.
- **review** for everything in between. An uncertain classifier must never silence an alert.

I set those numbers by replaying labelled alerts and reading where the classes separated. That is the point of having them in code.

## The second decision: guarding the page

The agent has two tools, `page_oncall` and `file_morning_note`. Before `page_oncall` runs, a Strands `InterventionHandler.before_tool_call` sends the alert plus the proposed page back to Decider 2B with two yes/no questions: does the message only state facts found in the alert, and does the alert justify waking a human right now? Unfaithful gets a `Guide` (rewrite it from the alert only, at most twice). Unwarranted gets a `Deny`. Otherwise `Proceed`.

Same client, same server, a different state. That is what made the pattern feel reusable: the client and the policy shape stay, the state and the questions change.

## What I measured

I wrote 40 Grafana webhook payloads modelled on my real alert rules and labelled each one with what I, the on-call engineer, would want: 14 page, 12 review, 14 drop. Then I replayed them through the gate, with the decider on CPU on an EC2 c7i.4xlarge (my account had no GPU quota in time), and through Amazon Nova 2 Lite and Nova Pro, given the same policy text and asked the same three-way question.

| Decision maker | Matches engineer | Real pages silenced | Median latency | Billed tokens |
| --- | --- | --- | --- | --- |
| Strands Decider 2B, 2 questions, CPU (c7i.4xlarge) | 36 / 40 | 0 | 1,520 ms | none |
| Amazon Nova 2 Lite, same policy in the prompt | 36 / 40 | 0 | 427 ms | 9,898 in, 320 out |
| Amazon Nova Pro, same policy in the prompt | 36 / 40 | 0 | 416 ms | 8,461 in, 86 out |

All three run in us-east-1 on the same 40 alerts. Accuracy is a tie. On a CPU, the decider is slower than a Bedrock call, and I'm saying so plainly. The strands-decider docs report about 115 ms on an RTX 3090 and about 150 ms on an M3 MacBook, but I could not measure those here. The decider wins on three other counts:

- **No per-call bill.** Every alert passes through the gate, and 10 of the 40 are dropped without ever reaching Bedrock.
- **A dial instead of a word.** The wake answer is a calibrated probability, so the page line is a number in code:

| Page line | Real pages caught | False pages |
| --- | --- | --- |
| 0.70 | 14 / 14 | 7 |
| 0.75 | 14 / 14 | 3 |
| **0.77** (shipped) | **14 / 14** | **2** |
| 0.80 | 13 / 14 | 2 |
| 0.85 | 12 / 14 | 1 |

- **It stays in your network.** The alert text goes to a model you run.

The thresholds were tuned on these same 40 alerts, so treat them as a starting point, not a result. The 4 misses are 2 scrape alerts for a laptop and a dev container, which paged, and a phone and a flapping probe, which went to review. Nothing real was ever dropped.

Going from four questions to two cut CPU latency from 2.4 s to 1.5 s with no loss in accuracy. On a CPU every question is a forward pass. The strands-decider docs say extra questions are nearly free on a GPU.

Bedrock only sees the alerts that pass the gate, and those are the ones where a well-written brief is worth paying for.

## What I learned

- **Write the option descriptions, not just the question.** My first version asked four questions with generic options and matched my own verdict 17 times out of 40. Putting my on-call policy into the descriptions of a single yes/no ("a laptop or phone or dev container" is a no), plus a simpler policy, took it to 36.
- **Not every answer is useful.** A four-level urgency score came back between 1.5 and 1.9 for nearly every alert. The yes/no probability separated the classes cleanly: every real page scored at least 0.77, and every morning note at least 0.5. I dropped the questions the policy did not need.
- **On a CPU, questions are not free.** Each question cost about 700 ms on a 16 vCPU instance, so going from four to two cut latency from 2.4 s to 1.5 s. The docs say extra questions are nearly free on a GPU. Ask only what you branch on.
- **Benchmark fairly.** My first Nova baseline scored badly. Then I noticed it had a one-line prompt while the decider had my policy in its option descriptions. With the same text, Nova tied. The decider's case is not that it is smarter. It is cheaper per call, it runs where your alerts are, and it hands you a number you can turn like a dial.
- **Keep the LLM for what it is good at.** Nova writes a better brief than I would at 3 am. It should not be the one deciding whether it is 3 am.

## Try it

Source, the reusable pattern and the fixtures: REPO_URL

The pattern is one file, `hush/decider_policy.py`, with no dependency beyond the standard library and a running `strands-decider serve`. Rewrite `render_state` for your payload, put your on-call policy in the option descriptions, replay a labelled sample, move the thresholds. Then point a Grafana contact point at `/webhook` and sleep.

Demo video: VIDEO_URL
