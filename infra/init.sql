-- CPD schema: job tracker + retail sales model + quarantine + S3 raw lake.
-- Idempotent: safe to re-run against existing DBs (worker/API also run it on startup).
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
-- S3 object key of the archived raw file (empty for jobs ingested before S3 archival).
ALTER TABLE etl_jobs ADD COLUMN IF NOT EXISTS s3_key TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_etl_jobs_status ON etl_jobs(status);
CREATE INDEX IF NOT EXISTS idx_etl_jobs_created ON etl_jobs(created_at DESC);

-- Reference catalog (validated by ETL joins; seeded below)
CREATE TABLE IF NOT EXISTS products (
  sku TEXT PRIMARY KEY,
  product_name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stores (
  store_id TEXT PRIMARY KEY,
  store_name TEXT NOT NULL DEFAULT ''
);

-- One row per accepted order line. order_id is globally unique:
-- a cross-file repeat is quarantined as duplicate_order_id, never double-counted.
CREATE TABLE IF NOT EXISTS sales_orders (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES etl_jobs(id) ON DELETE CASCADE,
  order_id TEXT NOT NULL UNIQUE,
  order_date DATE NOT NULL,
  store_id TEXT NOT NULL REFERENCES stores(store_id),
  sku TEXT NOT NULL REFERENCES products(sku),
  qty INT NOT NULL,
  unit_price NUMERIC(12,2) NOT NULL,
  currency CHAR(3) NOT NULL,
  unit_price_usd NUMERIC(12,2) NOT NULL,
  line_total_usd NUMERIC(14,2) NOT NULL,
  customer_id TEXT NOT NULL,
  payment_method TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sales_orders_job ON sales_orders(job_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_date ON sales_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_sales_orders_store ON sales_orders(store_id);

-- Quarantine: every rejected row with machine-readable reason.
CREATE TABLE IF NOT EXISTS rejected_rows (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES etl_jobs(id) ON DELETE CASCADE,
  row_number INT NOT NULL,
  order_id TEXT NOT NULL DEFAULT '',
  raw_line TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rejected_job ON rejected_rows(job_id);

INSERT INTO products (sku, product_name, category) VALUES
  ('SKU-1', 'Apple', 'Produce'),
  ('SKU-2', 'Bread', 'Bakery'),
  ('SKU-3', 'Milk', 'Dairy'),
  ('SKU-4', 'Eggs', 'Dairy'),
  ('SKU-5', 'Coffee', 'Beverages')
ON CONFLICT (sku) DO NOTHING;

INSERT INTO stores (store_id, store_name) VALUES
  ('S-01', 'Downtown'),
  ('S-02', 'Uptown'),
  ('S-03', 'Airport')
ON CONFLICT (store_id) DO NOTHING;
