-- Phase 1 schema: job tracker. Real sales tables come in Phase 2.
CREATE TABLE IF NOT EXISTS etl_jobs (
  id UUID PRIMARY KEY,
  filename TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  file_size BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  progress_pct INT NOT NULL DEFAULT 0,
  rows_total INT NOT NULL DEFAULT 0,
  rows_ok INT NOT NULL DEFAULT 0,
  rows_rejected INT NOT NULL DEFAULT 0,
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_etl_jobs_status ON etl_jobs(status);
CREATE INDEX IF NOT EXISTS idx_etl_jobs_created ON etl_jobs(created_at DESC);
