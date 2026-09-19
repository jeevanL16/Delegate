# n8n Notification Workflow — Delegate: Resolve

This document specifies the n8n workflow configuration for **Delegate: Resolve** notifications per §1.1 and §13 of `MASTER_BUILD_PROMPT.md`.

---

## 1. Architectural Boundary

> [!IMPORTANT]
> **n8n Scope Boundary (§1.1):**
> - The core ticket pipeline (`Analyzer → Router → Executor → Reviewer`) runs **synchronously in plain Python inside a single FastAPI request handler**.
> - **n8n does NOT orchestrate, trigger, or sit inside the pipeline.**
> - The model never receives n8n as a tool it can call.
> - Only two backend tools (`escalate_to_human`, `notify_customer`) make **one plain synchronous HTTP POST** to the n8n webhook URL *after* the Policy Engine has approved the action and the DB write has succeeded.
> - Calls are wrapped in try/except with a 5-second timeout, best-effort: a failed notification is logged to `audit_log` (`action="n8n_notify_failed"`) but **never alters the ticket's already-correct DB state**.

---

## 2. Workflow Specification

### Workflow Name: `delegate-resolve-notifications`

### Workflow Diagram
```text
┌─────────────────────────────────────────────────────────────┐
│ Webhook Node (POST)                                         │
│ Header Auth: X-Delegate-Secret == N8N_WEBHOOK_SECRET         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Switch Node: Filter on {{ $json.body.type }}                │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
        type == "escalation"           type == "notify_customer"
               │                              │
               ▼                              ▼
┌─────────────────────────────┐┌──────────────────────────────┐
│ Slack Node                  ││ Email Node (SMTP / SES)      │
│ Channel: #support-escalated ││ To: {{ $json.customer_email }}│
│ Message: Ticket ID, reason, ││ Template lookup based on     │
│ customer name, summary      ││ {{ $json.template }} enum    │
└─────────────────────────────┘└──────────────────────────────┘
```

---

## 3. Node Configuration Details

### 1. Webhook Node
- **HTTP Method:** `POST`
- **Path:** `/webhook/delegate-resolve`
- **Authentication:** Header Auth
  - **Header Name:** `X-Delegate-Secret`
  - **Header Value:** Must match `N8N_WEBHOOK_SECRET` from `.env`
- **Response Mode:** `When Last Node Finishes` (or `Immediately` with `200 OK`)

### 2. Switch Node
- **Condition:** String comparison on `{{ $json.body.type }}`
- **Rules:**
  - Rule 1: Value equals `escalation` → Output 0 (Slack Notification)
  - Rule 2: Value equals `notify_customer` → Output 1 (Customer Email)

### 3. Slack Node (Escalations)
- **Triggered by:** `type == "escalation"`
- **Inbound Payload:**
  ```json
  {
    "type": "escalation",
    "ticket_id": "8f286741-5770-44a0-a3ea-bb184daba425",
    "customer_name": "Priya Nair",
    "reason": "customer_flagged",
    "summary": "VIP customer refund request escalated for human review."
  }
  ```
- **Slack Message Block:**
  ```text
  🚨 *Ticket Escalated to Human Queue*
  • *Ticket ID:* `{{ $json.body.ticket_id }}`
  • *Customer:* {{ $json.body.customer_name }}
  • *Reason:* `{{ $json.body.reason }}`
  • *Summary:* {{ $json.body.summary }}
  • *Action Required:* Open Streamlit Human Queue to review and approve/close.
  ```

### 4. Email Node (Customer Notification)
- **Triggered by:** `type == "notify_customer"`
- **Inbound Payload:**
  ```json
  {
    "type": "notify_customer",
    "ticket_id": "8f286741-5770-44a0-a3ea-bb184daba425",
    "customer_email": "arjun@example.com",
    "template": "refund_issued"
  }
  ```
- **Template Lookup (server-side in n8n code node, NO free-text bodies permitted):**
  - `refund_issued`:
    - Subject: `Update regarding your support ticket #{{ $json.body.ticket_id.slice(0,8) }}`
    - Body: `Hello, your refund has been approved and processed to your original payment method. Please allow 3-5 business days for it to reflect in your account.`
  - `escalated`:
    - Subject: `Your support ticket #{{ $json.body.ticket_id.slice(0,8) }} has been escalated`
    - Body: `Hello, your request requires additional review by our specialist team. A human agent will contact you shortly.`
  - `info_needed`:
    - Subject: `Additional information needed for ticket #{{ $json.body.ticket_id.slice(0,8) }}`
    - Body: `Hello, we need additional details to resolve your inquiry. Please reply with the required information.`

---

## 4. Testing the Webhook

### Local curl verification:
```bash
curl -X POST http://localhost:5678/webhook/delegate-resolve \
  -H "Content-Type: application/json" \
  -H "X-Delegate-Secret: your_configured_secret" \
  -d '{
    "type": "escalation",
    "ticket_id": "aaaa0001-0000-0000-0000-000000000001",
    "customer_name": "Arjun Sharma",
    "reason": "amount_over_cap",
    "summary": "Refund amount exceeds $100 policy cap"
  }'
```
Expected response: `200 OK`
