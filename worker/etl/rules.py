"""Shared Retail ETL rules: catalog, FX, limits, column contract.

Single source of truth for validation. Keep in sync with infra/init.sql
(catalog seeds) and samples/README.md (defect taxonomy).
"""
from decimal import Decimal

HEADER = ["order_id", "order_date", "store_id", "sku", "product_name",
          "category", "qty", "unit_price", "currency", "customer_id", "payment_method"]
N_COLS = len(HEADER)

# sku -> (product_name, category); name match is case-insensitive, trimmed.
CATALOG = {
    "SKU-1": ("Apple", "Produce"),
    "SKU-2": ("Bread", "Bakery"),
    "SKU-3": ("Milk", "Dairy"),
    "SKU-4": ("Eggs", "Dairy"),
    "SKU-5": ("Coffee", "Beverages"),
}

STORES = {"S-01", "S-02", "S-03"}

# Static FX to USD (documented in samples/README.md).
FX_TO_USD = {"USD": Decimal("1.0"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27")}

PAYMENTS = {"card", "cash"}  # compared lower-cased after trim

MAX_QTY = 100_000  # above this is implausible_qty

# Lenient date inputs (all normalized to date). Anything else -> invalid_date.
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")
