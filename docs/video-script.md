# Demo video script (target 2:30, hard cap 3:00)

Screen: one terminal, large font. Phone screen-mirrored or on camera for the ntfy pushes.

## 0:00 Problem (20 s)

Show a phone full of old ntfy alerts, or the Grafana alert list.

"This is my homelab's Grafana. Every alert goes to my phone. Most of them are noise: resolved notices, my laptop leaving the tailnet, a backup report. After a while you stop reading, and that is how you miss the real one."

## 0:20 What Hush does (25 s)

Show the README diagram.

"Hush sits between Grafana and my phone. Strands Decider 2B reads each alert and answers two typed questions: should a human be woken at 3am, and what kind of event is this. It returns calibrated probabilities, not text. A dozen lines of Python turn those into drop, review or page. Only review and page go to a Strands agent on Amazon Bedrock, Nova 2 Lite, which writes a three-sentence brief and calls a tool."

## 0:45 Live run (75 s)

Run the demo (one command, see below). Narrate as it scrolls:

1. Backup finished: "wake 0.40. Dropped. No LLM call."
2. Web service down, RESOLVED: "The severity label says critical, but the decider reads the status. Wake 0.41, dropped."
3. Root filesystem at 97 percent on db1: "Wake 0.89. Page. Nova writes the brief. Before the page goes out, a Strands intervention asks the decider again: is the message faithful to the alert, is a page warranted? Both yes, proceed." Phone buzzes.
4. PostgreSQL down: page, phone buzzes.
5. Test alert: dropped.
6. Laptop left the tailnet: "Wake 0.71, between the lines. Not a page, a note for the morning."
7. Vault sealed: page, phone buzzes.

End line: "7 alerts: 3 paged, 1 filed for the morning, 3 dropped with no LLM call."

## 2:00 The numbers (25 s)

Show the Results table in the README.

"On 40 labelled alerts the decider matched my verdict 36 times and never silenced a real page. Nova, given the same policy, also scored 36, and it is faster than the decider on this CPU box. What the decider gives me is no per-call bill and a probability I can turn like a dial: at 0.77 it catches all 14 real pages with 2 false ones."

## 2:25 The reusable pattern (20 s)

Show `hush/decider_policy.py`, scrolled to QUESTIONS and policy().

"The pattern is one file: render your payload to text, put your on-call policy in the option descriptions, keep the thresholds in code and test them. Link in the article."

## 2:45 End

"Hush. The model classifies, the code decides, Bedrock writes, and I sleep."

## How to run the demo on camera

The decider and agent run on the EC2 host. From your terminal:

```sh
ssh -t -i /private/tmp/claude-501/-Users-sumon-SumonMSelim/5a770201-73f1-4d9b-89bf-9ae45358b3bf/scratchpad/hush_key \
  -o UserKnownHostsFile=/private/tmp/claude-501/-Users-sumon-SumonMSelim/5a770201-73f1-4d9b-89bf-9ae45358b3bf/scratchpad/known_hosts \
  ubuntu@44.222.249.79 '~/demo.sh hush-grafana'
```

It takes about 30 seconds. Run it once before recording to warm up.
