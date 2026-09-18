"""CPD API Phase 2: uploads, job tracking, quarantine downloads, sales reads."""
import csv
import hashlib
import io
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
# psycopg (sync) wants plain DSN, not SQLAlchemy prefix
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/uploads"))
QUEUE_KEY = "cpd:queue"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "infra" / "init.sql"

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def pg():
    return psycopg.connect(PG_DSN)


def ensure_schema():
    with pg() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()  # upgrades pre-Phase-2 volumes; fresh DBs also get init.sql
    yield


app = FastAPI(title="CPD ETL API (Phase 2)", lifespan=lifespan)

JOB_COLS = ("id, filename, file_size, status, progress_pct, rows_total, rows_ok,"
            " rows_rejected, error_summary, created_at, updated_at")


def _filters(alias: str, date_from, date_to, store_id):
    conds, args = [], []
    if date_from:
        conds.append(f"{alias}order_date >= %s")
        args.append(date_from)
    if date_to:
        conds.append(f"{alias}order_date <= %s")
        args.append(date_to)
    if store_id:
        conds.append(f"{alias}store_id = %s")
        args.append(store_id)
    return (f"WHERE {' AND '.join(conds)}" if conds else "", args)


def error_breakdown(conn, job_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT reason, COUNT(*) FROM rejected_rows WHERE job_id=%s"
                    " GROUP BY reason ORDER BY COUNT(*) DESC", (job_id,))
        return {row[0]: row[1] for row in cur.fetchall()}


@app.get("/api/health")
def health():
    checks = {"api": "ok"}
    try:
        with pg() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    try:
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@app.post("/api/uploads")
def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx", ".json")):
        raise HTTPException(400, "Only .csv / .xlsx / .json accepted")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{job_id}_{Path(file.filename).name}"
    sha = hashlib.sha256()
    size = 0
    with dest.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
            f.write(chunk)
    digest = sha.hexdigest()
    with pg() as conn, conn.cursor() as cur:
        # Idempotency: same file content returns existing job
        cur.execute("SELECT id FROM etl_jobs WHERE file_sha256=%s ORDER BY created_at DESC LIMIT 1", (digest,))
        row = cur.fetchone()
        if row:
            conn.commit()
            dest.unlink(missing_ok=True)
            return {"job_id": str(row[0]), "deduped": True}
        cur.execute(
            "INSERT INTO etl_jobs (id, filename, file_sha256, file_size, status) VALUES (%s,%s,%s,%s,'QUEUED')",
            (job_id, file.filename, digest, size),
        )
        conn.commit()
    r.rpush(QUEUE_KEY, job_id)
    return {"job_id": job_id, "deduped": False}


@app.get("/api/jobs")
def list_jobs(limit: int = 50):
    with pg() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {JOB_COLS} FROM etl_jobs ORDER BY created_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    with pg() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {JOB_COLS} FROM etl_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        cols = [d[0] for d in cur.description]
        body = dict(zip(cols, row))
        body["error_breakdown"] = error_breakdown(conn, job_id)
        return body


@app.get("/api/jobs/{job_id}/errors.csv")
def job_errors_csv(job_id: str):
    with pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM etl_jobs WHERE id=%s", (job_id,))
        if not cur.fetchone():
            raise HTTPException(404, "job not found")
        cur.execute("SELECT row_number, order_id, reason, raw_line FROM rejected_rows"
                    " WHERE job_id=%s ORDER BY row_number", (job_id,))
        rows = cur.fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row_number", "order_id", "reason", "raw_line"])
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(iter([data]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={job_id}_errors.csv"})


@app.get("/api/jobs/{job_id}/rows")
def job_rows(job_id: str, limit: int = 50):
    with pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM etl_jobs WHERE id=%s", (job_id,))
        if not cur.fetchone():
            raise HTTPException(404, "job not found")
        cur.execute("SELECT order_id, order_date, store_id, sku, qty, unit_price,"
                    " currency, unit_price_usd, line_total_usd, customer_id, payment_method"
                    " FROM sales_orders WHERE job_id=%s ORDER BY order_id LIMIT %s",
                    (job_id, min(limit, 500)))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/api/sales/summary")
def sales_summary(date_from: str | None = None, date_to: str | None = None,
                  store_id: str | None = None):
    where, args = _filters("", date_from, date_to, store_id)
    where_o, args_o = _filters("o.", date_from, date_to, store_id)
    with pg() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*), COALESCE(SUM(line_total_usd),0) FROM sales_orders {where}", args)
        n, revenue = cur.fetchone()
        cur.execute(f"SELECT order_date::text, COUNT(*), SUM(line_total_usd) FROM sales_orders"
                    f" {where} GROUP BY order_date ORDER BY order_date", args)
        by_day = [{"date": d, "orders": c, "revenue_usd": str(s)} for d, c, s in cur.fetchall()]
        cur.execute(f"SELECT p.category, COUNT(*), SUM(o.line_total_usd) FROM sales_orders o"
                    f" JOIN products p ON p.sku=o.sku {where_o}"
                    f" GROUP BY p.category ORDER BY SUM(o.line_total_usd) DESC",
                    args_o)
        by_category = [{"category": c, "orders": n_, "revenue_usd": str(s)} for c, n_, s in cur.fetchall()]
    return {"orders": n, "revenue_usd": str(revenue), "by_day": by_day, "by_category": by_category}
