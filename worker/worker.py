"""CPD Worker Phase 1: pop job ids from Redis, simulate staged ETL progress.

Phase 2 will replace the sleep loop with real parse/validate/transform/load
for the Retail sales CSV, writing to products/orders tables and quarantine.
"""
import os
import time
from pathlib import Path

import psycopg
import redis

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/uploads"))
QUEUE_KEY = "cpd:queue"

STAGES = [
    ("PARSING", 15),
    ("VALIDATING", 40),
    ("TRANSFORMING", 65),
    ("LOADING", 90),
]

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def update(job_id, status, pct, rows_total=0, rows_ok=0, rows_rejected=0, err=""):
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_jobs SET status=%s, progress_pct=%s, rows_total=%s, rows_ok=%s,"
            " rows_rejected=%s, error_summary=%s, updated_at=now() WHERE id=%s",
            (status, pct, rows_total, rows_ok, rows_rejected, err, job_id),
        )
        conn.commit()


def count_rows(job_id: str) -> int:
    for p in UPLOAD_DIR.glob(f"{job_id}_*"):
        try:
            with p.open("r", errors="ignore") as f:
                return max(0, sum(1 for _ in f) - 1)  # minus header
        except OSError:
            return 0
    return 0


def process(job_id: str):
    total = count_rows(job_id)
    for status, pct in STAGES:
        update(job_id, status, pct, rows_total=total)
        time.sleep(2)  # stand-in for real work
    # Phase 1: pretend all rows pass
    update(job_id, "COMPLETED", 100, rows_total=total, rows_ok=total)


def main():
    print("worker up, waiting on", QUEUE_KEY, flush=True)
    while True:
        item = r.brpop(QUEUE_KEY, timeout=5)
        if not item:
            continue
        _, job_id = item
        print(f"processing {job_id}", flush=True)
        try:
            process(job_id)
            print(f"done {job_id}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"failed {job_id}: {e}", flush=True)
            try:
                update(job_id, "FAILED", 100, err=str(e)[:500])
            except Exception:
                pass


if __name__ == "__main__":
    main()
