#!/usr/bin/env python3
"""Deterministic Retail-sales CSV generator for CPD scale tests.

Usage:
  python3 generate.py --rows 10000 --dirty-ratio 0.05 --seed 42 --out sales_scale_10k.csv
  python3 generate.py --rows 100000 --dirty-ratio 0.05 --seed 7 --out sales_scale_100k.csv

Clean rows cycle the SKU/store catalog; dirty rows are injected every
Nth row (N derived from dirty-ratio) rotating through the defect pool so
rejected-row counts are exactly reproducible. See manifest.json / README.
Stdlib only.
"""
import argparse
import csv
import random

HEADER = ["order_id", "order_date", "store_id", "sku", "product_name",
          "category", "qty", "unit_price", "currency", "customer_id", "payment_method"]

CATALOG = [
    ("SKU-1", "Apple", "Produce", 1.50),
    ("SKU-2", "Bread", "Bakery", 3.00),
    ("SKU-3", "Milk", "Dairy", 2.20),
    ("SKU-4", "Eggs", "Dairy", 0.35),
    ("SKU-5", "Coffee", "Beverages", 8.99),
]
STORES = ["S-01", "S-02", "S-03"]
CURRENCIES = ["USD", "USD", "USD", "EUR", "GBP"]
PAYMENTS = ["card", "cash"]


def dirty_variant(row: list, pick: int) -> list:
    r = list(row)
    mode = pick % 8
    if mode == 0:
        r[1] = "bad-date"          # unparseable date
    elif mode == 1:
        r[6] = "-3"                # negative qty
    elif mode == 2:
        r[3] = "SKU-999"           # unknown SKU
    elif mode == 3:
        r[7] = ""                  # missing price
    elif mode == 4:
        r[0] = ""                  # missing order_id
    elif mode == 5:
        r[8] = "XYZ"               # unknown currency
    elif mode == 6:
        r[10] = "bitcoin"          # unknown payment
    elif mode == 7:
        r[6] = "0"                 # zero qty
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10000)
    ap.add_argument("--dirty-ratio", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="sales_scale_10k.csv")
    ap.add_argument("--start-id", type=int, default=900001)
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    step = max(1, int(round(1.0 / a.dirty_ratio))) if a.dirty_ratio > 0 else 0
    dirty_n = 0
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(a.rows):
            oid = a.start_id + i
            day = (i % 28) + 1
            sku, name, cat, price = CATALOG[i % len(CATALOG)]
            row = [f"O-{oid}", f"2026-09-{day:02d}", STORES[i % len(STORES)],
                   sku, name, cat, str(rnd.randint(1, 12)), f"{price:.2f}",
                   CURRENCIES[i % len(CURRENCIES)], f"C-{(i % 500) + 1:04d}",
                   PAYMENTS[i % len(PAYMENTS)]]
            if step and i % step == step - 1:
                row = dirty_variant(row, dirty_n)
                dirty_n += 1
            w.writerow(row)
    print(f"wrote {a.out}: rows={a.rows} dirty={dirty_n} seed={a.seed}")


if __name__ == "__main__":
    main()
