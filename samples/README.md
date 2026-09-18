# CPD Sample Datasets — Retail Sales

Deterministic fixtures for upload → ETL → status testing.
Machine-readable expectations live in `manifest.json` (assert these in Phase-2 tests).

## Schema

`order_id,order_date,store_id,sku,product_name,category,qty,unit_price,currency,customer_id,payment_method`

Reference catalog (Phase-2 joins validate against this):

* SKUs: `SKU-1 Apple/Produce`, `SKU-2 Bread/Bakery`, `SKU-3 Milk/Dairy`, `SKU-4 Eggs/Dairy`, `SKU-5 Coffee/Beverages`
* Stores: `S-01`, `S-02`, `S-03`
* Currencies: `USD`, `EUR`, `GBP` (FX-normalized in Transform: EUR×1.08, GBP×1.27)
* Payments: `card`, `cash` (case-insensitive, trimmed)
* Rules: qty integer 1–100,000 · price Decimal > 0 · dates accept `YYYY-MM-DD`, `MM/DD/YYYY`, ISO datetime · `order_id` unique per file and globally (repeats quarantined, never double-counted) · `product_name` must match catalog (case-insensitive) · `category` carried through, not validated

## Files

| File | Rows | Purpose |
|---|---|---|
| `sales_good.csv` | 20 ok / 0 rejected | Happy path: upload → COMPLETED, includes EUR/GBP rows for FX |
| `sales_good.json` | 20 (same rows) | JSON parser path; same expectations as good CSV |
| `sales_dirty.csv` | 26 total: 8 ok / 18 rejected | Validation matrix: every defect class at least once |
| `sales_edge.csv` | 13 total: 10 ok / 3 rejected | Parser hardening boundaries (see below) |
| `sales_scale_10k.csv` | 10,000 (500 dirty, seed 42) | Scale test: `worker=3`, progress bar, throughput |
| `generate.py` | — | Regenerate scale files deterministically (stdlib only) |
| `manifest.json` | — | Expected counts for automated tests (verified by running `worker/etl/validate` over the fixtures) |

## Dirty-file defect map (`sales_dirty.csv`)

Rejected (18): duplicate full row (O-2001 ×2) · conflicting duplicate `O-2015` (2 dates) · invalid dates (`bad-date`, month 13) · negative qty · zero qty · unknown SKU-999 · unknown store S-99 · empty price · unparseable price · unknown currency XYZ · unknown payment `bitcoin` · empty `order_id` · empty `product_name` · empty `customer_id` · non-empty extra column (O-2024) · short row · implausible qty 1,000,000.

Valid-by-design (8, parser must be lenient here): `O-2016` mixed date `09/06/2026` · `O-2017` uppercase `CARD` · `O-2018` lowercase `usd` · `O-2019` padded `  Bread  ` (trim) · `O-2020` trailing comma (empty extra field ignored) · `O-2015` first occurrence · `O-2001` first occurrence · `O-2023` clean control row.

## Edge file (`sales_edge.csv`, 13 rows, 10 ok / 3 rejected)

Accepted: leap-day 2024-02-29 · 3-decimal price · unicode customer id · case variants (`Cash`, `APPLE`) · ISO datetime · padded fields · GBP row · repeating decimal · month-end date.
Rejected: zero price (price must be > 0) · max-int qty (implausible) · SKU/name mismatch (`SKU-1`/`Banana`).

## Regenerate / scale up

```bash
python3 generate.py --rows 10000 --dirty-ratio 0.05 --seed 42 --out sales_scale_10k.csv
python3 generate.py --rows 100000 --dirty-ratio 0.05 --seed 7 --out sales_scale_100k.csv  # gitignored, on-demand
```

Every Nth row (`N = 1/dirty-ratio`) is dirty, rotating 8 defect modes — counts are exact.
Idempotency test: re-upload any file; API dedupes by `file_sha256` and returns the existing job.
