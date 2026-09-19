# Delegate: Resolve — Assumptions & Architectural Decisions

This document records all architectural choices, provider selections, and judgment calls made during the build of **Delegate: Resolve** per `MASTER_BUILD_PROMPT.md`.

---

## 1. LLM Provider: Groq (Primary) & Gemini (Fallback)

**Decision:** Groq (`llama-3.3-70b-versatile`) is selected as the default LLM provider.

- **Rationale:** Groq provides ultra-fast inference and a generous free tier with reliable JSON mode and OpenAI-compatible native tool calling (`tools` parameter with function definitions).
- **Fallback:** Google Gemini (`gemini-1.5-flash`) is supported via the OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`) by setting `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`.
- **Abstraction:** `app/agent/llm_client.py` provides provider-agnostic interfaces (`call_llm_json`, `call_llm_tools`, `extract_tool_calls`), ensuring pipeline stages (Analyzer, Router, Executor, Reviewer) do not contain vendor-specific SDK logic.

---

## 2. Currency: INR (₹1000.00 Refund Cap)

**Decision:** The system strictly uses Indian Rupees (INR), stored internally as integer paise/cents (`amount_cents`).

- `REFUND_CAP_CENTS=100000` (₹1000.00) is enforced server-side by the Policy Engine.
- The DB schema stores `amount_cents` in `orders` and `refunds`.
- Amounts displayed in the UI and logs are formatted as `₹XX.XX`.
- Refund amounts are always extracted directly from the verified database record (`orders.amount_cents`), never accepted from model-supplied tool arguments.

---

## 3. Cognee Memory Integration & Graceful Degradation

**Decision:** Memory integration uses Cognee (`cognee>=0.1.17`) encapsulated exclusively in `app/agent/memory.py`.

- **Workflow:**
  - `recall(customer_id, query)`: Called before Router execution. Retrieves top-3 structured summaries for the customer and injects them inside a `<past_context>` block explicitly labeled as untrusted background context.
  - `remember(ticket_record)`: Called after Reviewer completes its database write. Asynchronously persists structured metadata (`ticket_id`, `customer_id`, `issue_type`, `outcome`, `action_taken`, `timestamp`).
- **Graceful Degradation:**
  - If `COGNEE_LLM_API_KEY` is not provided, the module seamlessly falls back to an in-memory session store (`_fallback_store`).
  - SDK calls are wrapped in exception handlers with timeouts; memory failures never block or compromise the ticket resolution lifecycle.

---

## 4. n8n Outbound Notification Webhook

**Decision:** n8n acts solely as an external notification sink per §1.1.

- **Scope Boundary:** n8n does not orchestrate, trigger, or schedule pipeline operations. The LLM never sees or calls n8n.
- **Trigger Points:** Only `escalate_to_human` and `notify_customer` perform a synchronous HTTP POST with header `X-Delegate-Secret: N8N_WEBHOOK_SECRET` and a 5-second timeout.
- **Fail-Closed Guarantee:** Any HTTP error or timeout is logged to `audit_log` with `action="n8n_notify_failed"`. The ticket's database state is already committed and remains correct.

---

## 5. Synchronous Pipeline Execution

**Decision:** All four stages (`Analyzer → Router → Executor → Reviewer`) run synchronously within a single FastAPI request handler.

- **Rationale:** At this scale, synchronous execution in a threadpool guarantees deterministic state transitions, avoids distributed state issues, simplifies testing, and ensures atomic audit logging.
- **Fail-Closed Error Handling:** If an uncaught exception occurs during pipeline execution, the route handler intercepts it and returns `200 OK` with `status: "escalated"` and `escalation_reason: "internal_error"`, guaranteeing no failure silently drops into an unmonitored state.

---

## 6. Database & Test Fixtures

- **Production:** PostgreSQL 15+ with Alembic migrations (`app/db/migrations`).
- **Automated Tests:** SQLite in-memory / local (`sqlite:///./test_delegate.db`) used for rapid, isolated `pytest` runs via cross-database compatible SQLAlchemy types (`TypeDecorator`).
- **Security Check:** Policy engine enforcement is validated with 38 unit, integration, golden-ticket, and adversarial red-team tests.
