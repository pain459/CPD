"""CPD API: uploads (volume + S3 raw lake), job tracking, SSE progress,
quarantine downloads, sales reads."""
import asyncio
import csv
import hashlib
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

import s3util

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
# psycopg (sync) wants plain DSN, not SQLAlchemy prefix
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/uploads"))
QUEUE_KEY = "cpd:queue"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "infra" / "init.sql"
STAGING_DIR = UPLOAD_DIR / ".staging"
DEFAULT_CHUNK_SIZE = 1024 * 1024
MIN_CHUNK_SIZE = 8 * 1024
MAX_CHUNK_SIZE = 8 * 1024 * 1024

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def pg():
    return psycopg.connect(PG_DSN)


def ensure_schema():
    with pg() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()  # upgrades older volumes; fresh DBs also get init.sql
    try:
        s = s3util.settings()
        s3util.ensure_bucket(s3util.client(), s["bucket"])
    except Exception as e:  # S3 (RustFS) may lag behind api on first boot
        print(f"warn: S3 bucket ensure failed, uploads will retry per-request: {e}", flush=True)
    try:
        # Drop staging state for sessions abandoned >24h ago (refresh-proof, not leak-proof).
        with pg() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM upload_sessions WHERE status='open'"
                        " AND updated_at < now() - interval '24 hours'")
            for (sid,) in cur.fetchall():
                (STAGING_DIR / f"{sid}.part").unlink(missing_ok=True)
            cur.execute("UPDATE upload_sessions SET status='abandoned' WHERE status='open'"
                        " AND updated_at < now() - interval '24 hours'")
            conn.commit()
    except Exception as e:
        print(f"warn: stale upload cleanup failed: {e}", flush=True)
    yield


app = FastAPI(title="CPD ETL API", lifespan=lifespan)

JOB_COLS = ("id, filename, file_size, status, progress_pct, rows_total, rows_ok,"
            " rows_rejected, error_summary, s3_key, created_at, updated_at")

TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}


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
    try:
        s = s3util.settings()
        s3util.client().head_bucket(Bucket=s["bucket"])
        checks["s3"] = "ok"
    except Exception as e:
        checks["s3"] = f"error: {e}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    body = {"status": status, "checks": checks}
    try:
        state = r.get("cpd:scaler")
        body["autoscaler"] = json.loads(state) if state else None
    except Exception:
        body["autoscaler"] = None
    return body


def _register_job(dest: Path, filename: str, size: int, digest: str) -> dict:
    """Shared finish path: dedupe -> S3 archive -> job row -> enqueue.

    Returns {"job_id", "deduped"}. Consumes dest (deleted on dedupe/Failure).
    """
    with pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM etl_jobs WHERE file_sha256=%s ORDER BY created_at DESC LIMIT 1", (digest,))
        row = cur.fetchone()
        conn.commit()
        if row:
            dest.unlink(missing_ok=True)
            return {"job_id": str(row[0]), "deduped": True}
    job_id = str(uuid.uuid4())
    final = UPLOAD_DIR / f"{job_id}_{Path(filename).name}"
    if dest != final:
        dest.rename(final)
    s = s3util.settings()
    key = s3util.key_for(job_id, filename)
    try:
        cli = s3util.client()
        s3util.ensure_bucket(cli, s["bucket"])
        s3util.put_file(cli, s["bucket"], key, final)
    except Exception as e:
        final.unlink(missing_ok=True)
        raise HTTPException(502, f"S3 raw-lake write failed: {e}")
    with pg() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO etl_jobs (id, filename, file_sha256, file_size, status, s3_key)"
            " VALUES (%s,%s,%s,%s,'QUEUED',%s)",
            (job_id, filename, digest, size, key),
        )
        conn.commit()
    r.rpush(QUEUE_KEY, job_id)
    return {"job_id": job_id, "deduped": False}


@app.post("/api/uploads")
def upload(file: UploadFile = File(...)):
    """Single-shot upload (curl-friendly). Browser UI uses resumable sessions."""
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx", ".json")):
        raise HTTPException(400, "Only .csv / .xlsx / .json accepted")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}"
    sha = hashlib.sha256()
    size = 0
    with tmp.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
            f.write(chunk)
    return _register_job(tmp, file.filename, size, sha.hexdigest())


# ---------------- resumable uploads (survive browser refresh) ----------------

def _session_or_404(cur, upload_id: str):
    cur.execute("SELECT id, filename, size, chunk_size, total_chunks, sha256, received, status"
                " FROM upload_sessions WHERE id=%s", (upload_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "upload session not found")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


@app.post("/api/uploads/resumable/init")
def resumable_init(payload: dict):
    filename = (payload.get("filename") or "").strip()
    size = int(payload.get("size") or 0)
    sha256 = (payload.get("sha256") or "").strip().lower()
    chunk_size = int(payload.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    if not filename or not filename.lower().endswith((".csv", ".xlsx", ".json")):
        raise HTTPException(400, "Only .csv / .xlsx / .json accepted")
    if size <= 0:
        raise HTTPException(400, "size must be positive")
    chunk_size = max(MIN_CHUNK_SIZE, min(MAX_CHUNK_SIZE, chunk_size))
    total_chunks = (size + chunk_size - 1) // chunk_size
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    with pg() as conn, conn.cursor() as cur:
        # Resume an identical open session instead of starting over.
        cur.execute("SELECT id FROM upload_sessions WHERE filename=%s AND size=%s"
                    " AND sha256=%s AND status='open' ORDER BY updated_at DESC LIMIT 1",
                    (filename, size, sha256))
        row = cur.fetchone()
        if row:
            conn.commit()
            sess = _session_or_404(cur, str(row[0]))
            sess["received"] = sess["received"] or []
            return {"upload_id": sess["id"], "resumed": True, **{k: sess[k] for k in ("total_chunks", "chunk_size", "received")}}
        upload_id = str(uuid.uuid4())
        (STAGING_DIR / f"{upload_id}.part").touch()
        cur.execute(
            "INSERT INTO upload_sessions (id, filename, size, chunk_size, total_chunks, sha256)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            (upload_id, filename, size, chunk_size, total_chunks, sha256),
        )
        conn.commit()
    return {"upload_id": upload_id, "resumed": False, "total_chunks": total_chunks,
            "chunk_size": chunk_size, "received": []}


@app.put("/api/uploads/resumable/{upload_id}/chunks/{index}")
async def resumable_chunk(upload_id: str, index: int, request: Request):
    body = await request.body()
    with pg() as conn, conn.cursor() as cur:
        sess = _session_or_404(cur, upload_id)
        if sess["status"] != "open":
            raise HTTPException(409, f"session is {sess['status']}")
        if not 0 <= index < sess["total_chunks"]:
            raise HTTPException(400, "chunk index out of range")
        if len(body) > sess["chunk_size"]:
            raise HTTPException(400, "chunk bigger than session chunk_size")
        part = STAGING_DIR / f"{upload_id}.part"
        with part.open("r+b") as f:
            f.seek(index * sess["chunk_size"])
            f.write(body)
        received = set(sess["received"] or []) | {index}
        cur.execute("UPDATE upload_sessions SET received=%s::jsonb, updated_at=now() WHERE id=%s",
                    (json.dumps(sorted(received)), upload_id))
        conn.commit()
    return {"upload_id": upload_id, "index": index, "received_count": len(received),
            "total_chunks": sess["total_chunks"]}


@app.get("/api/uploads/resumable/{upload_id}")
def resumable_status(upload_id: str):
    with pg() as conn, conn.cursor() as cur:
        sess = _session_or_404(cur, upload_id)
        conn.commit()
    sess["received"] = sess["received"] or []
    return sess


@app.post("/api/uploads/resumable/{upload_id}/complete")
def resumable_complete(upload_id: str):
    with pg() as conn, conn.cursor() as cur:
        sess = _session_or_404(cur, upload_id)
        if sess["status"] != "open":
            raise HTTPException(409, f"session is {sess['status']}")
        missing = set(range(sess["total_chunks"])) - set(sess["received"] or [])
        if missing:
            raise HTTPException(400, f"missing chunks: {sorted(missing)[:10]}")
        part = STAGING_DIR / f"{upload_id}.part"
        if not part.exists() or part.stat().st_size < sess["size"]:
            raise HTTPException(400, "assembled file smaller than declared size")
        # Authoritative server-side hash (client sha is only a resume hint).
        sha = hashlib.sha256()
        with part.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                sha.update(chunk)
        digest = sha.hexdigest()
        cur.execute("UPDATE upload_sessions SET status='complete', updated_at=now() WHERE id=%s",
                    (upload_id,))
        conn.commit()
    try:
        return _register_job(part, sess["filename"], sess["size"], digest)
    finally:
        part.unlink(missing_ok=True)


@app.delete("/api/uploads/resumable/{upload_id}")
def resumable_abandon(upload_id: str):
    with pg() as conn, conn.cursor() as cur:
        sess = _session_or_404(cur, upload_id)
        cur.execute("UPDATE upload_sessions SET status='abandoned', updated_at=now() WHERE id=%s",
                    (upload_id,))
        conn.commit()
    (STAGING_DIR / f"{upload_id}.part").unlink(missing_ok=True)
    return {"upload_id": upload_id, "status": "abandoned", "filename": sess["filename"]}


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


@app.get("/api/jobs/{job_id}/raw")
def job_raw(job_id: str):
    """Download the archived raw file: local volume first, S3 lake fallback."""
    with pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT filename, s3_key FROM etl_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        filename, s3_key = row
    for cand in UPLOAD_DIR.glob(f"{job_id}_*"):
        return StreamingResponse(cand.open("rb"), media_type="application/octet-stream",
                                 headers={"Content-Disposition": f"attachment; filename={filename}"})
    if not s3_key:
        raise HTTPException(404, "raw file not found (pre-S3 job, volume miss)")
    try:
        s = s3util.settings()
        data = s3util.get_bytes(s3util.client(), s["bucket"], s3_key)
    except Exception as e:
        raise HTTPException(502, f"S3 raw-lake read failed: {e}")
    return StreamingResponse(iter([data]), media_type="application/octet-stream",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


def _job_payload(job_id: str) -> dict | None:
    with pg() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {JOB_COLS} FROM etl_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        body = dict(zip(cols, row))
        body["error_breakdown"] = error_breakdown(conn, job_id)
        return body


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE stream of job progress; closes after the terminal state is sent."""

    async def gen():
        while True:
            payload = await asyncio.to_thread(_job_payload, job_id)
            if payload is None:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            if payload["status"] in TERMINAL:
                return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
