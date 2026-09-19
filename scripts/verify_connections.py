"""Standalone Connectivity Verification Script — Delegate: Resolve

Checks connectivity to:
1. Neon PostgreSQL Database (via app.db.session)
2. n8n Outbound Webhook (via settings.n8n_webhook_url and secret)
3. Local Backend API (optional ping to http://localhost:8000/health)

Usage:
  python scripts/verify_connections.py
"""
import os
import sys
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import text
import requests

from app.config import settings
from app.db.models import Customer, Order, Refund
from app.db.session import SessionLocal, engine


def check_database() -> bool:
    print("=" * 60)
    print("1. DATABASE CONNECTIVITY CHECK")
    print("=" * 60)
    # Mask database password in output
    db_url_display = settings.database_url
    if "@" in db_url_display and ":" in db_url_display:
        parts = db_url_display.split("@")
        prefix = parts[0].split(":")
        masked = f"{prefix[0]}:****@{parts[1]}"
    else:
        masked = db_url_display
    print(f"Target URL: {masked}")

    try:
        with SessionLocal() as db:
            result = db.execute(text("SELECT 1")).scalar()
            if result != 1:
                print("❌ [FAIL] Database returned unexpected query result.")
                return False
            
            cust_count = db.query(Customer).count()
            order_count = db.query(Order).count()
            refund_count = db.query(Refund).count()

            print("✅ [OK] Database (Neon PostgreSQL) connected successfully!")
            print(f"     • Customers: {cust_count} rows")
            print(f"     • Orders:    {order_count} rows")
            print(f"     • Refunds:   {refund_count} rows")
            return True
    except Exception as exc:
        print(f"❌ [FAIL] Database connection failed!")
        print(f"     Error: {exc}")
        print("     Hint: Check DATABASE_URL in .env, SSL mode (sslmode=require), and network access.")
        return False


def check_n8n_webhook() -> bool:
    print("\n" + "=" * 60)
    print("2. N8N OUTBOUND WEBHOOK CONNECTIVITY CHECK")
    print("=" * 60)
    url = settings.n8n_webhook_url
    secret = settings.n8n_webhook_secret

    if not url:
        print("⚠️ [WARN] N8N_WEBHOOK_URL is not set in .env. Skipping n8n check.")
        return False

    print(f"Target URL: {url}")
    print(f"Secret Header: {'Configured (X-Delegate-Secret)' if secret else 'None'}")

    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Delegate-Secret"] = secret

    payload = {
        "event_type": "connectivity_test",
        "message": "Delegate: Resolve connectivity probe",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=8)
        if resp.status_code in (200, 201, 204):
            print(f"✅ [OK] n8n Webhook is reachable and accepting secret! (HTTP {resp.status_code})")
            print(f"     Response body: {resp.text[:120]}")
            return True
        elif resp.status_code == 401 or resp.status_code == 403:
            print(f"❌ [FAIL] n8n Webhook returned HTTP {resp.status_code} Unauthorized!")
            print("     Hint: Verify N8N_WEBHOOK_SECRET in .env matches the Header Auth node in n8n.")
            return False
        elif resp.status_code == 404:
            print(f"❌ [FAIL] n8n Webhook returned HTTP 404 Not Found!")
            print("     Hint: Verify the n8n workflow is published and the webhook URL path is correct.")
            return False
        else:
            print(f"⚠️ [WARN] n8n Webhook returned HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("❌ [FAIL] n8n Webhook timed out after 8 seconds.")
        print("     Hint: Check if your n8n instance is awake or suspended.")
        return False
    except Exception as exc:
        print(f"❌ [FAIL] n8n Webhook connection error: {exc}")
        return False


def check_local_api() -> None:
    print("\n" + "=" * 60)
    print("3. LOCAL BACKEND API CHECK (OPTIONAL)")
    print("=" * 60)
    try:
        resp = requests.get("http://localhost:8000/health", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ [OK] Local FastAPI backend is online at http://localhost:8000 (status={data.get('status')}, db={data.get('db')})")
        else:
            print(f"⚠️ [WARN] Local backend returned HTTP {resp.status_code}")
    except requests.exceptions.ConnectionError:
        print("ℹ️ [INFO] Local backend is not running on port 8000 (normal if running standalone DB script).")


def main() -> None:
    db_ok = check_database()
    n8n_ok = check_n8n_webhook()
    check_local_api()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Database:    {'✅ Connected' if db_ok else '❌ Error'}")
    print(f"n8n Webhook: {'✅ Reachable' if n8n_ok else '❌ Error'}")
    print("=" * 60)

    if not db_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
