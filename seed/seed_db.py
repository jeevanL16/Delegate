"""Seed script — loads customers.json and orders.json into the database.

Includes 10 fixed baseline demo customers (1-10) and 10 randomized scenario customers (11-20).
Idempotent upsert by UUID — safe to re-run multiple times or mid-demo.
Use --randomize to re-generate randomized order amounts within policy-appropriate bands.
"""
import argparse
import json
import os
import random
import sys
import uuid
from pathlib import Path
from typing import cast

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app.db.models import Base, Customer, Order
from app.db.session import SessionLocal, engine

SEED_DIR = Path(__file__).parent

# 10 Randomized Demo Customer specifications
RANDOM_CUSTOMERS_SPEC = [
    {
        "id": "cccc0011-0000-0000-0000-000000000011",
        "name": "Ananya Rao",
        "email": "ananya.rao@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0023-0000-0000-0000-000000000023",
        "status": "failed",
        "band": (2500, 8500),  # Under ₹100 cap
        "note_template": "failed order, under cap (auto-refund eligible)",
        "expected_outcome": "Auto-refund eligible (under ₹100 cap)",
    },
    {
        "id": "cccc0012-0000-0000-0000-000000000012",
        "name": "Rohan Verma",
        "email": "rohan.verma@example.in",
        "tier": "vip",
        "flags": [],
        "order_id": "dddd0024-0000-0000-0000-000000000024",
        "status": "failed",
        "band": (2500, 8500),  # Under cap, VIP
        "note_template": "failed order, VIP customer",
        "expected_outcome": "Escalates to Human (VIP policy)",
    },
    {
        "id": "cccc0013-0000-0000-0000-000000000013",
        "name": "Sneha Kulkarni",
        "email": "sneha.kulkarni@example.in",
        "tier": "regular",
        "flags": ["repeat_complainer"],
        "order_id": "dddd0025-0000-0000-0000-000000000025",
        "status": "failed",
        "band": (2500, 8500),  # Under cap, repeat complainer
        "note_template": "failed order, repeat complainer",
        "expected_outcome": "Escalates to Human (repeat complainer)",
    },
    {
        "id": "cccc0014-0000-0000-0000-000000000014",
        "name": "Suresh Iyer",
        "email": "suresh.iyer@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0026-0000-0000-0000-000000000026",
        "status": "failed",
        "band": (11000, 25000),  # Over ₹100 cap
        "note_template": "failed order, over cap",
        "expected_outcome": "Escalates to Human (over ₹100 cap)",
    },
    {
        "id": "cccc0015-0000-0000-0000-000000000015",
        "name": "Meera Joshi",
        "email": "meera.joshi@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0027-0000-0000-0000-000000000027",
        "status": "refunded",
        "band": (3000, 7000),
        "note_template": "already refunded order",
        "expected_outcome": "Denied / Already Refunded",
    },
    {
        "id": "cccc0016-0000-0000-0000-000000000016",
        "name": "Siddharth Sen",
        "email": "siddharth.sen@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0028-0000-0000-0000-000000000028",
        "status": "delivered",
        "band": (2000, 6000),
        "note_template": "delivered order",
        "expected_outcome": "Informational / Delivered order",
    },
    {
        "id": "cccc0017-0000-0000-0000-000000000017",
        "name": "Kavita Pillai",
        "email": "kavita.pillai@example.in",
        "tier": "vip",
        "flags": [],
        "order_id": "dddd0029-0000-0000-0000-000000000029",
        "status": "pending",
        "band": (4000, 9000),
        "note_template": "pending fulfillment, VIP customer",
        "expected_outcome": "Escalates to Human (VIP policy)",
    },
    {
        "id": "cccc0018-0000-0000-0000-000000000018",
        "name": "Rahul Bhatt",
        "email": "rahul.bhatt@example.in",
        "tier": "regular",
        "flags": ["repeat_complainer"],
        "order_id": "dddd0030-0000-0000-0000-000000000030",
        "status": "failed",
        "band": (12000, 22000),  # Over cap & repeat complainer
        "note_template": "failed order, repeat complainer & over cap",
        "expected_outcome": "Escalates to Human (repeat + over cap)",
    },
    {
        "id": "cccc0019-0000-0000-0000-000000000019",
        "name": "Pooja Hegde",
        "email": "pooja.hegde@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0031-0000-0000-0000-000000000031",
        "status": "failed",
        "band": (2500, 8500),  # Under ₹100 cap
        "note_template": "failed order, under cap (auto-refund eligible)",
        "expected_outcome": "Auto-refund eligible (under ₹100 cap)",
    },
    {
        "id": "cccc0020-0000-0000-0000-000000000020",
        "name": "Rajesh Nambiar",
        "email": "rajesh.nambiar@example.in",
        "tier": "regular",
        "flags": [],
        "order_id": "dddd0032-0000-0000-0000-000000000032",
        "status": "pending",
        "band": (1500, 5000),
        "note_template": "pending fulfillment order",
        "expected_outcome": "Informational / Pending order",
    },
]


def load_json(filename: str) -> list[dict]:
    path = SEED_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(filename: str, data: list[dict]) -> None:
    path = SEED_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def sync_seed_data(randomize: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    """Synchronize customers and orders, adding or re-randomizing the 10 scenario customers."""
    customers_data = load_json("customers.json")
    orders_data = load_json("orders.json")

    existing_cust_ids = {c["id"] for c in customers_data}
    existing_order_map = {o["id"]: o for o in orders_data}

    summary_rows = []

    for spec in RANDOM_CUSTOMERS_SPEC:
        cid = spec["id"]
        oid = spec["order_id"]

        # Ensure customer exists
        if cid not in existing_cust_ids:
            new_cust = {
                "id": cid,
                "name": spec["name"],
                "email": spec["email"],
                "tier": spec["tier"],
                "flags": spec["flags"],
            }
            customers_data.append(new_cust)
            existing_cust_ids.add(cid)

        # Generate or retain order amount
        needs_random = randomize or (oid not in existing_order_map)
        if needs_random:
            low, high = cast(tuple[int, int], spec["band"])
            # Generate amount in multiples of 10 or 50 cents
            amount_cents = random.randint(low // 50, high // 50) * 50
            note = f"₹{amount_cents/100:.2f} — {spec['note_template']}"
            order_entry = {
                "id": oid,
                "customer_id": cid,
                "amount_cents": amount_cents,
                "status": spec["status"],
                "note": note,
            }
            existing_order_map[oid] = order_entry
        else:
            order_entry = existing_order_map[oid]

        flags_list = cast(list[str], spec["flags"])
        flags_str = f" [{', '.join(flags_list)}]" if flags_list else ""
        tier_flags = f"{spec['tier']}{flags_str}"
        summary_rows.append({
            "name": spec["name"],
            "tier_flags": tier_flags,
            "amount_cents": order_entry["amount_cents"],
            "status": order_entry["status"],
            "expected_outcome": spec["expected_outcome"],
        })

    # Reassemble orders preserving original order + new orders
    base_orders = [o for o in orders_data if o["id"] not in existing_order_map]
    all_orders = base_orders + list(existing_order_map.values())

    save_json("customers.json", customers_data)
    save_json("orders.json", all_orders)

    return customers_data, all_orders, summary_rows


def print_ascii_summary(summary_rows: list[dict]) -> None:
    """Print clean ASCII summary table of the 10 demo users."""
    headers = ["Customer Name", "Tier / Flags", "Order (₹)", "Expected Outcome"]
    rows = [
        [
            r["name"],
            r["tier_flags"],
            f"₹{r['amount_cents']/100:,.2f}",
            r["expected_outcome"],
        ]
        for r in summary_rows
    ]

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "|" + "|".join(f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))) + "|"

    print("\n" + "=" * len(sep))
    print(" 10 RANDOMIZED DEMO CUSTOMER SCENARIOS")
    print("=" * len(sep))
    print(sep)
    print(header_line)
    print(sep)
    for row in rows:
        line = "|" + "|".join(f" {row[i].ljust(col_widths[i])} " for i in range(len(row))) + "|"
        print(line)
    print(sep + "\n")


def seed(randomize: bool = False) -> None:
    # Ensure tables exist (creates tables if not already migrated)
    Base.metadata.create_all(bind=engine)

    customers_data, orders_data, summary_rows = sync_seed_data(randomize=randomize)

    db = SessionLocal()
    try:
        # ── Seed customers (upsert) ───────────────────────────────────────────
        inserted_customers = 0
        updated_customers = 0
        for c in customers_data:
            cust_id = uuid.UUID(c["id"])
            existing = db.get(Customer, cust_id)
            if existing is None:
                customer = Customer(
                    id=cust_id,
                    name=c["name"],
                    email=c["email"],
                    tier=c["tier"],
                    flags=c.get("flags", []),
                )
                db.add(customer)
                inserted_customers += 1
            else:
                existing.name = c["name"]
                existing.email = c["email"]
                existing.tier = c["tier"]
                existing.flags = c.get("flags", [])
                updated_customers += 1
        db.flush()
        print(f"✅ Customers: {inserted_customers} inserted, {updated_customers} updated ({len(customers_data)} total in database)")

        # ── Seed orders (upsert) ──────────────────────────────────────────────
        inserted_orders = 0
        updated_orders = 0
        for o in orders_data:
            order_id = uuid.UUID(o["id"])
            cust_id = uuid.UUID(o["customer_id"])
            existing = db.get(Order, order_id)
            if existing is None:
                order = Order(
                    id=order_id,
                    customer_id=cust_id,
                    amount_cents=o["amount_cents"],
                    status=o["status"],
                )
                db.add(order)
                inserted_orders += 1
            else:
                existing.customer_id = cust_id
                existing.amount_cents = o["amount_cents"]
                existing.status = o["status"]
                updated_orders += 1
        db.flush()
        print(f"✅ Orders: {inserted_orders} inserted, {updated_orders} updated ({len(orders_data)} total in database)")

        db.commit()
        print("✅ Database seed complete.")

        # Print ASCII summary table
        print_ascii_summary(summary_rows)

    except Exception as exc:
        db.rollback()
        print(f"❌ Seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Delegate: Resolve demo database")
    parser.add_argument(
        "--randomize",
        action="store_true",
        help="Re-randomize order amounts for the 10 demo scenario customers within policy bands",
    )
    args = parser.parse_args()
    seed(randomize=args.randomize)
