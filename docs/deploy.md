# Deployment Guide — Delegate: Resolve

This guide walks you through deploying **Delegate: Resolve** to **Render** with a **Neon PostgreSQL** database, **Groq** LLM, and **n8n** webhook notifications.

---

## Architecture Overview

```
[ Customer / Agent ] ──> [ Chainlit UI (Port 8000 / $PORT) ]
                               │ (HTTP via API_BASE_URL)
                               ▼
                        [ FastAPI Backend (Port 8000 / $PORT) ]
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
      [ Neon PostgreSQL ]  [ Groq LLM ]  [ n8n Webhook ]
      (Customers/Orders)   (Resolution)  (Customer Notify)
```

- **Backend (`delegate-api`)**: FastAPI service running on Uvicorn. Exposes `/tickets`, `/human`, and `/health`.
- **Frontend (`delegate-ui`)**: Chainlit web app providing Customer Support Chat with visible reasoning and Staff Console.
- **Database**: Remote Neon PostgreSQL database (SSL required: `sslmode=require`).
- **Policy Engine**: Server-enforced rules (₹100 refund cap, 5-tool ceiling, VIP/repeat-complainer escalation).

---

## 1. Prerequisites

Before deploying, ensure you have:
1. **GitHub Repository**: Push this codebase to your GitHub account.
2. **Neon PostgreSQL Database**: Create a free serverless PostgreSQL database at [neon.tech](https://neon.tech). Obtain the pooled connection string:
   ```
   postgresql+psycopg://user:password@ep-xxxx-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```
3. **Groq Cloud API Key**: Sign up at [console.groq.com](https://console.groq.com) and generate an API key.
4. **n8n Instance (Optional / Recommended)**: An n8n Cloud or self-hosted webhook configured for `POST` requests with header secret verification (`X-Delegate-Secret`).
5. **Render Account**: Create a free account at [render.com](https://render.com).

---

## 2. Option A: One-Click Blueprint Deployment (Recommended)

The repository includes a ready-to-use `render.yaml` specification.

1. Navigate to **Render Dashboard** > **New +** > **Blueprint**.
2. Connect your GitHub repository containing `Delegate`.
3. Render will parse `render.yaml` and discover two services:
   - `delegate-api` (Backend Web Service)
   - `delegate-ui` (Frontend Web Service)
4. Populate the missing environment variables in the Render Blueprint UI:
   - `DATABASE_URL`: Your Neon PostgreSQL connection string.
   - `GROQ_API_KEY`: Your Groq API key (`gsk_...`).
   - `N8N_WEBHOOK_URL`: Your n8n webhook URL.
   - `N8N_WEBHOOK_SECRET`: The shared secret configured in your n8n workflow.
5. Click **Apply**. Render will build and deploy both services automatically.

---

## 3. Option B: Manual Service Deployment

If you prefer to configure services individually in Render:

### Service 1: Backend API (`delegate-api`)
- **Type**: Web Service
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/health`
- **Environment Variables**:
  | Key | Example / Default | Description |
  |---|---|---|
  | `DATABASE_URL` | `postgresql+psycopg://...` | Neon PostgreSQL pooled URL with SSL |
  | `SERVICE_API_KEY` | `4a2c9f8e1d5b3a7c6e0f2d4b8a1c3e5f` | Shared secret for `/tickets` API |
  | `HUMAN_JWT_SECRET` | `7f9b2d4e6a8c0e1f3a5b7c9d1e3f...` | 64-char key for human JWT verification |
  | `LLM_PROVIDER` | `groq` | Primary LLM provider |
  | `GROQ_API_KEY` | `gsk_...` | Groq API Key |
  | `LLM_MODEL` | `llama-3.3-70b-versatile` | Groq model identifier |
  | `REFUND_CAP_CENTS` | `100000` | Max auto-approved refund (₹1000.00) |
  | `MAX_TOOL_CALLS_PER_TICKET` | `5` | Tool loop ceiling |
  | `MAX_REFUNDS_PER_TICKET` | `1` | Max refunds per ticket |
  | `N8N_WEBHOOK_URL` | `https://.../webhook/delegate-notify` | Outbound n8n notification URL |
  | `N8N_WEBHOOK_SECRET` | `your_n8n_secret...` | Header secret for n8n |
  | `CORS_ORIGINS` | `*` | Allowed CORS origins |
  | `ENVIRONMENT` | `production` | Environment name |
  | `LOG_LEVEL` | `INFO` | Logging level |

### Service 2: Frontend UI (`delegate-ui`)
- **Type**: Web Service
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `chainlit run ui/chainlit_app.py --host 0.0.0.0 --port $PORT`
- **Environment Variables**:
  | Key | Example / Value | Description |
  |---|---|---|
  | `DATABASE_URL` | `postgresql+asyncpg://...` | Neon PostgreSQL for conversation thread persistence |
  | `API_BASE_URL` | `https://delegate-api.onrender.com` | Public URL of `delegate-api` service |
  | `SERVICE_API_KEY` | *(same as delegate-api)* | Shared API key for tickets |
  | `HUMAN_JWT_SECRET` | *(same as delegate-api)* | Shared secret for generating human JWTs |
  | `CHAINLIT_AUTH_SECRET` | *(random 64-char secret)* | Secret for signing Chainlit auth session cookies |
  | `SHOW_REASONING_TO_CUSTOMER` | `true` | Show/hide the internal reasoning steps to customers (demo only) |
  | `DEMO_MODE` | `true` | Allows 'demo123' password login instead of real auth (demo only) |

---

## 4. Post-Deployment Database Initialization

Once deployed, populate the Neon PostgreSQL database with the demo customers and transactions.

From your local machine (or Render SSH / Shell):
```bash
# 1. Verify connections to Neon DB and n8n webhook
python scripts/verify_connections.py

# 2. Seed database with 20 demo customers and 32 orders
python seed/seed_db.py --randomize
```

The script will output an ASCII table detailing the 10 demo scenario users:
```
=====================================================================================================
 10 RANDOMIZED DEMO CUSTOMER SCENARIOS
=====================================================================================================
+----------------+-----------------------------+-----------+----------------------------------------+
| Customer Name  | Tier / Flags                | Order (₹) | Expected Outcome                       |
+----------------+-----------------------------+-----------+----------------------------------------+
| Ananya Rao     | regular                     | ₹84.50    | Auto-refund eligible (under ₹100 cap)  |
| Rohan Verma    | vip                         | ₹72.50    | Escalates to Human (VIP policy)        |
| Sneha Kulkarni | regular [repeat_complainer] | ₹80.00    | Escalates to Human (repeat complainer) |
| Suresh Iyer    | regular                     | ₹167.00   | Escalates to Human (over ₹100 cap)     |
| Meera Joshi    | regular                     | ₹47.00    | Denied / Already Refunded              |
| Siddharth Sen  | regular                     | ₹52.50    | Informational / Delivered order        |
| Kavita Pillai  | vip                         | ₹80.00    | Escalates to Human (VIP policy)        |
| Rahul Bhatt    | regular [repeat_complainer] | ₹171.00   | Escalates to Human (repeat + over cap) |
| Pooja Hegde    | regular                     | ₹39.50    | Auto-refund eligible (under ₹100 cap)  |
| Rajesh Nambiar | regular                     | ₹39.50    | Informational / Pending order          |
+----------------+-----------------------------+-----------+----------------------------------------+
```

---

## 5. Verifying Deployment Health

1. **Backend Health Check**:
   Open `https://delegate-api.onrender.com/health` in your browser. Expected response:
   ```json
   {"status": "ok", "db": true, "environment": "production"}
   ```
2. **Frontend Support Chat**:
   Open `https://delegate-ui.onrender.com` in your browser.
   - Verify the top green status indicators (`API: online`, `DB: connected`).
   - Select **Ananya Rao** from the dropdown. Notice order `#dddd0023…` with amount in `₹`.
   - Send: `"My payment failed and I was charged. Please refund."`
   - Observe real-time resolution and confirmation message.
3. **Escalation & Human Review**:
   - Select **Rohan Verma** (VIP). Send a refund request.
   - Observe escalation: *"Thanks for your patience — I've looped in a specialist..."*
   - Navigate to **👥 Human Queue** tab.
   - Inspect the escalated ticket with audit trail, enter an approval note, and issue refund.

---

## 6. Common Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `DB: error` on `/health` | Missing `sslmode=require` or network block | Ensure connection string includes `?sslmode=require&channel_binding=require`. |
| `API offline` in Streamlit | Incorrect `API_BASE_URL` | Ensure `API_BASE_URL` in `delegate-ui` has no trailing slash (`https://delegate-api.onrender.com`). |
| `Invalid API Key` (401) | `SERVICE_API_KEY` mismatch | Ensure `SERVICE_API_KEY` matches exactly in both API and UI services. |
| Port binding error on Render | Hardcoded port | Uvicorn must start with `--port $PORT` and Streamlit with `--server.port $PORT`. |
