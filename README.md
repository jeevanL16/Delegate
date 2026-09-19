# Delegate: Resolve

An AI teammate that resolves customer support tickets end-to-end: it looks up
order context, takes real backend actions (refunds, ticket updates,
notifications), and escalates to a human whenever policy requires it.

## Why this isn't just a chatbot
It takes actions, not just answers. Every action passes through a
server-side policy engine that independently re-verifies amounts, ownership,
and caps before anything executes — the model proposes, the backend
disposes. Full audit trail on every decision.

## Architecture
A synchronous Python pipeline — Analyzer -> Router -> Executor -> Reviewer —
backed by Groq/Gemini tool use, with a policy engine as the sole
authorization chokepoint. n8n is used only as an outbound notification
webhook (Slack/email) called after policy approval; Cognee is used only for
ticket-memory recall/store. Neither orchestrates the pipeline. See
`docs/blueprint.md` for the full spec.

```
Customer Ticket (untrusted text)
        │
        ▼
 ┌───────────────┐
 │   ANALYZER    │  Extracts structured fields. Output schema-validated.
 │               │  Flags suspected injection. Cognee.recall() adds past-
 │               │  ticket context here as labeled, untrusted background info.
 └───────────────┘
        │
        ▼
 ┌───────────────┐
 │    ROUTER     │  Chooses tool(s) or routes straight to escalation
 └───────────────┘
        │
        ▼
 ┌───────────────┐
 │   EXECUTOR    │  Calls tools via LLM tool-use. Every side-effecting call
 │               │  passes through the Policy Engine (plain Python, not the
 │               │  model) before any DB write or external call.
 └───────────────┘
        │
        ▼
 ┌───────────────┐
 │   REVIEWER    │  Confirms outcome, finalizes ticket status.
 │               │  Cognee.remember() stores the outcome here.
 └───────────────┘
        │
        ▼
 Ticket resolved ──or── Escalated
        │
        ▼
 escalate_to_human / notify_customer tool ──(one sync HTTP POST)──► n8n webhook
                                                                       │
                                                          Slack message / templated email
```

## Security
All customer-submitted ticket text (and anything recalled from memory) is
treated as untrusted input. Defenses: strict data/instruction separation,
an injection-detection field on every Analyzer output, least-privilege
single-purpose tools, template-only outbound messaging, server-side
re-validation of every tool call, fail-closed defaults. A red-team suite
verifies 0 unauthorized actions across 7 adversarial tickets; CI blocks
merges if it fails.

## Local setup
1. `cp .env.example .env` and fill in your LLM key (`GROQ_API_KEY`) + n8n/Cognee values
2. `docker-compose -f infra/docker-compose.yml up -d postgres`
3. `pip install -r requirements.txt`
4. `alembic upgrade head`
5. `python seed/seed_db.py`
6. `uvicorn app.main:app --reload`
7. `streamlit run ui/streamlit_app.py`

## Tests
`pytest tests/ -v` — unit, integration, golden-ticket, and red-team suites (38/38 passing).

## Demo
See `docs/demo-script.md` — includes the memory-recall beat and the live
n8n Slack-notification beat.

## Metrics from our own test run
- 2/5 golden tickets auto-resolved without a human (remaining 3 escalated per policy: VIP tier, over-cap, ambiguous)
- Avg ~0.9s per ticket execution in automated testing
- Real actions taken across suites: refunds issued, status updates, notifications dispatched, and escalations recorded
- 7/7 adversarial tickets correctly escalated/blocked, 0 unauthorized actions
- 38/38 tests passing across unit, integration, golden-ticket, and red-team suites

## Known limitations
Single-org demo scope, mock orders/customers. Before real deployment: real
auth beyond a shared API key, compliance/legal review, production rate
limits on free LLM tiers.
