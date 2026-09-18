"""CPD Worker: Retail ETL — parse -> validate -> transform -> load.

Stages update etl_jobs progress so the single UI shows live status.
Final status: COMPLETED | COMPLETED_WITH_ERRORS | FAILED.
"""
import os
import traceback
from pathlib import Path

import psycopg
import redis

import s3util
from etl import db as etldb
from etl import parse as etlparse
from etl import transform as etltransform
from etl import validate as etlvalidate

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/uploads"))
QUEUE_KEY = "cpd:queue"

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def update(job_id, status, pct, rows_total=0, rows_ok=0, rows_rejected=0, err=""):
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_jobs SET status=%s, progress_pct=%s, rows_total=%s, rows_ok=%s,"
            " rows_rejected=%s, error_summary=%s, updated_at=now() WHERE id=%s",
            (status, pct, rows_total, rows_ok, rows_rejected, err, job_id),
        )
        conn.commit()


def find_upload(job_id: str) -> Path:
    """Volume first (fast local path); S3 raw lake fallback (survives volume loss)."""
    matches = list(UPLOAD_DIR.glob(f"{job_id}_*"))
    if matches:
        return matches[0]
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT filename, s3_key FROM etl_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
    if not row or not row[1]:
        raise FileNotFoundError(f"no upload found for job {job_id} (volume miss, no S3 key)")
    filename, key = row
    dest = UPLOAD_DIR / f"{job_id}_{Path(filename).name}"
    s = s3util.settings()
    s3util.download_file(s3util.client(), s["bucket"], key, dest)
    print(f"recovered {job_id} from S3 {key}", flush=True)
    return dest


def process(job_id: str):
    path = find_upload(job_id)
    with psycopg.connect(PG_DSN) as conn:
        etldb.ensure_schema(conn)
        conn.commit()

    update(job_id, "PARSING", 10)
    records = etlparse.read_any(path)
    total = len(records)
    if total == 0:
        update(job_id, "FAILED", 100, err="empty file: no data rows")
        return

    update(job_id, "VALIDATING", 35, rows_total=total)
    clean, rejected = etlvalidate.validate(records)

    update(job_id, "TRANSFORMING", 60, rows_total=total)
    enriched = [etltransform.enrich(row) for row in clean]

    update(job_id, "LOADING", 85, rows_total=total)
    with psycopg.connect(PG_DSN) as conn:
        etldb.ensure_schema(conn)
        ok, n_rej = etldb.load_job(conn, job_id, enriched, rejected)
        conn.commit()

    summary = etldb.error_summary(rejected)
    if ok == 0:
        update(job_id, "FAILED", 100, rows_total=total, rows_ok=0,
               rows_rejected=n_rej, err=summary or "all rows rejected")
    elif n_rej:
        update(job_id, "COMPLETED_WITH_ERRORS", 100, rows_total=total,
               rows_ok=ok, rows_rejected=n_rej, err=summary)
    else:
        update(job_id, "COMPLETED", 100, rows_total=total, rows_ok=ok)


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
            print(f"failed {job_id}: {e}\n{traceback.format_exc()}", flush=True)
            try:
                update(job_id, "FAILED", 100, err=str(e)[:500])
            except Exception:
                pass


if __name__ == "__main__":
    main()
