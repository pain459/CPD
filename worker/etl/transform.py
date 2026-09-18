"""Transform: FX normalization to USD + line totals (per-row, deterministic)."""
from decimal import Decimal, ROUND_HALF_UP

from .rules import FX_TO_USD
from .validate import CleanRow

_CENT = Decimal("0.01")


def to_usd(amount, currency: str):
    return (amount * FX_TO_USD[currency]).quantize(_CENT, rounding=ROUND_HALF_UP)


def enrich(row: CleanRow) -> dict:
    unit_usd = to_usd(row.unit_price, row.currency)
    total_usd = (unit_usd * row.qty).quantize(_CENT, rounding=ROUND_HALF_UP)
    return {
        "order_id": row.order_id,
        "order_date": row.order_date.isoformat(),
        "store_id": row.store_id,
        "sku": row.sku,
        "qty": row.qty,
        "unit_price": str(row.unit_price),
        "currency": row.currency,
        "unit_price_usd": str(unit_usd),
        "line_total_usd": str(total_usd),
        "customer_id": row.customer_id,
        "payment_method": row.payment_method,
    }
