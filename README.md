# Hush

**An on-call gatekeeper. Strands Decider 2B decides whether an alert may wake a human. Amazon Bedrock writes the brief for the ones that may.**

**Demo video (2:23):** https://youtu.be/c6Xigd2E96E

Built for the AWS Agent Experience Hackathon, decision pattern **#policy** (classify an incoming request before the agent acts on it), tags `#strands-decider-2b #policy`.

```
Grafana alert ──POST /webhook──▶ Hush
                                  │
                                  ├─ 1. Strands Decider 2B, self-hosted, one round trip
                                  │     wake a human? what kind of event?   → two calibrated numbers
                                  │
                                  ├─ 2. policy, plain Python
                                  │     drop   : confident noise or information, nobody woken, no LLM call
                                  │     review : worth a note for the morning
                                  │     page   : wake someone now
                                  │
                                  └─ 3. Strands agent on Amazon Bedrock (Nova 2 Lite), only for review and page
                                        writes a 3-sentence brief, calls page_oncall or file_morning_note
                                        before page_oncall runs, Decider 2B checks the page again:
                                        faithful to the alert? warranted?  → Proceed / Guide / Deny
```

## Why a decision model here

A homelab, like most small fleets, produces far more alerts than incidents. Most are resolved notices, flaps, test alerts, a laptop that left the tailnet. Sending every one of them through an LLM is slow, costs money, and an LLM asked "should I wake someone?" can be talked into either answer by the wording of the alert.

A decision model does not generate text. It reads the alert once and answers typed questions with calibrated probabilities. The code owns the thresholds. A silenced page is the worst outcome, so the policy drops an alert only when the model is confident it is noise, and sends anything it is unsure about to review, where the LLM and a human get to look.

The LLM still does what it is good at: turning a raw alert into three sentences a sleepy engineer can act on.

## The reusable pattern

[`hush/decider_policy.py`](hush/decider_policy.py) is the drop-in. It needs only the standard library and a running `strands-decider serve`.

```python
from hush.decider_policy import AlertGate

gate = AlertGate()                       # STRANDS_DECIDER_URL, default http://127.0.0.1:8099
verdict = gate.decide(grafana_webhook)   # one round trip, two questions on one state
if verdict.action == "drop":
    return                               # the model classified, the code decided
```

Three parts, each swappable on its own:

1. **State**: `render_state()` flattens the Grafana webhook (labels, annotations, status) to plain text. The decider encodes it once and shares it across all questions.
2. **Questions**: two typed questions in `QUESTIONS`. A `noul` (should the on-call engineer be woken at 3am?) and a `choice` (outage, degradation, security, noise, informational). The option descriptions are where your on-call policy lives ("a laptop or phone or dev container" is never worth waking for); write them as carefully as the questions.
3. **Policy**: `policy()` is ordinary control flow. Wake below 0.5 drops. Confident noise or information (choice confidence at least 0.5) drops unless wake reaches the page line. Wake at or above 0.77 pages unless the kind is confidently quiet. Everything in between goes to review, so an unsure classifier never silences an alert. `tests/test_policy.py` pins its behaviour.

The second use, in [`hush/agent.py`](hush/agent.py), is a Strands `InterventionHandler.before_tool_call` that re-asks the decider before the one tool that wakes a human. Same client, two `noul` questions, `Proceed` / `Guide` / `Deny`.

To use it on your own alerts: keep `AlertGate`, rewrite `render_state` for your payload, edit the option descriptions in `QUESTIONS`, run `python -m hush.replay` on a labelled sample and move the thresholds until the confusion matrix looks right for your pager.

## Results

Measured on the 40 fixture alerts in [`fixtures/alerts.json`](fixtures/alerts.json), modelled on a real homelab's Grafana rules and labelled by its on-call engineer (14 page, 12 review, 14 drop). Numbers from `python -m hush.replay` and `python -m hush.bench`, decider on CPU on an EC2 c7i.4xlarge in us-east-1 (no GPU quota on the account in time).

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

## Run it

You need a Strands Decider server and AWS credentials with Bedrock access (Amazon Nova 2 Lite by default, any Converse model via `HUSH_MODEL_ID`).

```sh
# 1. the decider. On Apple silicon (see strands-decider docs for CUDA or CPU):
git clone https://github.com/strands-labs/strands-decider
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e "strands-decider[mlx]" -e ".[dev]"
strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device mlx --port 8099

# 2. gate only, no AWS needed: verdicts, accuracy, latency
python -m hush.replay

# 3. the whole agent
export AWS_PROFILE=... AWS_REGION=us-east-1
export HUSH_NTFY_TOPIC=your-ntfy-topic     # leave unset for a dry run
python -m hush.server                       # http://127.0.0.1:8787/webhook
python -m hush.replay --serve               # replay the 40 alerts through it

# 4. the measurement: decider vs a Bedrock model classifying the same alerts
python -m hush.bench
```

`docker compose up` runs the same thing in two containers with the decider on CPU.

No local hardware? [`infra/decider-ec2.yml`](infra/decider-ec2.yml) is the CloudFormation stack this was measured on: one EC2 instance in its own VPC, SSH from one address only, an instance role limited to invoking Amazon Nova, and the decider as a systemd service on localhost. Delete the stack when you are done.

```sh
aws cloudformation create-stack --stack-name hush-demo --template-body file://infra/decider-ec2.yml \
  --capabilities CAPABILITY_IAM \
  --parameters ParameterKey=SshCidr,ParameterValue=$(curl -s https://checkip.amazonaws.com)/32 \
               ParameterKey=SshPublicKey,ParameterValue="$(cat your_key.pub)"
```

### Point Grafana at it

Grafana Alerting, Contact points, New, type Webhook, URL `http://<hush-host>:8787/webhook`. The payload Grafana sends is what `render_state` reads. Set `HUSH_NTFY_TOPIC` and pages arrive on your phone through [ntfy](https://ntfy.sh).

## Layout

| Path | What |
| --- | --- |
| `hush/decider_policy.py` | the reusable pattern: state, questions, policy, client |
| `hush/agent.py` | Strands agent on Bedrock, two tools, the page guard intervention |
| `hush/server.py` | FastAPI webhook |
| `hush/replay.py` | replay fixtures, score the gate |
| `hush/bench.py` | decider vs Bedrock on the same decision |
| `hush/demo.py` | seven curated alerts for the demo video |
| `infra/decider-ec2.yml` | CloudFormation: EC2 host for the decider and agent |
| `fixtures/alerts.json` | 40 labelled Grafana webhook payloads |
| `tests/` | policy and guard behaviour |

## Honest notes

Strands Decider 2B is experimental and so is this. The thresholds were tuned on the same 40 alerts they are scored on, from one fleet; measure yours before trusting the drop branch. The Nova baseline prompt carries the same policy text as the decider's option descriptions, so the comparison is like for like. The server binds to localhost and has no authentication. The page guard caps `Guide` retries at two so a stubborn model cannot loop.

MIT.
