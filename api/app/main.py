"""CPD API Phase 1: upload CSV, track jobs in Postgres, enqueue to Redis."""
import hashlib
import os
import uuid
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
# psycopg (sync) wants plain DSN, not SQLAlchemy prefix
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/uploads"))
QUEUE_KEY = "cpd:queue"

app = FastAPI(title="CPD ETL API (Phase 1)")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def pg():
    return psycopg.connect(PG_DSN)


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
        raise HTTPException(400, "Only .csv / .xlsx / .json accepted in Phase 1")
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
        cur.execute(
            "SELECT id, filename, file_size, status, progress_pct, rows_total, rows_ok,"
            " rows_rejected, error_summary, created_at, updated_at FROM etl_jobs"
            " ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    with pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, filename, file_size, status, progress_pct, rows_total, rows_ok,"
            " rows_rejected, error_summary, created_at, updated_at FROM etl_jobs WHERE id=%s",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
