"""DB helpers. Schema comes from /app/infra/init.sql (single source of truth,
copied into the image; same file Postgres runs on first init)."""

from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "infra" / "init.sql"


def ensure_schema(conn):
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def error_summary(rejected) -> str:
    from collections import Counter
    counts = Counter(r.reason for r in rejected)
    return "; ".join(f"{k}×{v}" for k, v in counts.most_common(5))


def load_job(conn, job_id: str, enriched: list[dict], rejected: list) -> tuple[int, int]:
    """Insert accepted rows + quarantine. Returns (rows_ok, rows_rejected).

    order_id is globally UNIQUE: a repeat from an earlier file is quarantined
    as duplicate_order_id instead of double-counted.
    """
    from .validate import Rejected

    ok = 0
    if enriched:
        ids = [r["order_id"] for r in enriched]
        with conn.cursor() as cur:
            cur.execute("SELECT order_id FROM sales_orders WHERE order_id = ANY(%s)", (ids,))
            dupes = {row[0] for row in cur.fetchall()}
        for r in enriched:
            if r["order_id"] in dupes:
                rejected.append(Rejected(0, r["order_id"], r["order_id"], "duplicate_order_id"))
        fresh = [r for r in enriched if r["order_id"] not in dupes]
        if fresh:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO sales_orders (job_id, order_id, order_date, store_id,"
                    " sku, qty, unit_price, currency, unit_price_usd, line_total_usd,"
                    " customer_id, payment_method)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (order_id) DO NOTHING",
                    [(job_id, r["order_id"], r["order_date"], r["store_id"], r["sku"],
                      r["qty"], r["unit_price"], r["currency"], r["unit_price_usd"],
                      r["line_total_usd"], r["customer_id"], r["payment_method"])
                     for r in fresh],
                )
                inserted = cur.rowcount
            ok = inserted if inserted >= 0 else len(fresh)
    if rejected:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO rejected_rows (job_id, row_number, order_id, raw_line, reason)"
                " VALUES (%s,%s,%s,%s,%s)",
                [(job_id, r.row_number, r.order_id, r.raw, r.reason) for r in rejected],
            )
    return ok, len(rejected)
