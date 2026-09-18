"""Row-level validation. Pure function over parsed records -> (clean, rejected).

Lenient by design (see samples/README.md): trim everywhere, case-insensitive
currency/payment/product-name, extra date formats, empty trailing CSV column
ignored. Strict on: unknown sku/store/currency/payment, bad dates, bad qty or
price, missing keys, malformed arity, within-file duplicate order_id.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .rules import CATALOG, DATE_FORMATS, FX_TO_USD, MAX_QTY, N_COLS, PAYMENTS, STORES


@dataclass
class CleanRow:
    order_id: str
    order_date: date
    store_id: str
    sku: str
    qty: int
    unit_price: Decimal
    currency: str
    customer_id: str
    payment_method: str


@dataclass
class Rejected:
    row_number: int
    order_id: str
    raw: str
    reason: str


def parse_date(s: str):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _as_int(s: str):
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None


def _as_price(s: str):
    try:
        return Decimal(s.strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def validate(records) -> tuple[list[CleanRow], list[Rejected]]:
    clean: list[CleanRow] = []
    rejected: list[Rejected] = []
    seen_ids: set[str] = set()

    def drop(rec, reason):
        oid = rec["fields"][0].strip() if rec["fields"] else ""
        rejected.append(Rejected(rec["row_number"], oid, rec["raw"], reason))

    for rec in records:
        f = rec["fields"]
        # --- arity -------------------------------------------------------
        if len(f) > N_COLS:
            if any(c.strip() != "" for c in f[N_COLS:]):
                drop(rec, "extra_column")
                continue
            f = f[:N_COLS]
        elif len(f) < N_COLS:
            drop(rec, "short_row")
            continue
        f = [c.strip() for c in f]
        (oid, raw_date, store, sku, pname, _cat, raw_qty, raw_price,
         raw_cur, customer, raw_pay) = f

        # --- keys --------------------------------------------------------
        if not oid:
            drop(rec, "missing_order_id")
            continue
        if not store or store not in STORES:
            drop(rec, "unknown_store")
            continue
        if not sku or sku not in CATALOG:
            drop(rec, "unknown_sku")
            continue
        if not pname:
            drop(rec, "missing_product_name")
            continue
        want_name, _want_cat = CATALOG[sku]
        if pname.lower() != want_name.lower():
            drop(rec, "product_mismatch")
            continue
        if not customer:
            drop(rec, "missing_customer_id")
            continue

        # --- date --------------------------------------------------------
        if not raw_date:
            drop(rec, "invalid_date")
            continue
        dt = parse_date(raw_date)
        if dt is None:
            drop(rec, "invalid_date")
            continue

        # --- qty ---------------------------------------------------------
        qty = _as_int(raw_qty)
        if qty is None:
            drop(rec, "invalid_qty")
            continue
        if qty <= 0:
            drop(rec, "negative_qty" if qty < 0 else "zero_qty")
            continue
        if qty > MAX_QTY:
            drop(rec, "implausible_qty")
            continue

        # --- price -------------------------------------------------------
        if raw_price == "":
            drop(rec, "missing_price")
            continue
        price = _as_price(raw_price)
        if price is None:
            drop(rec, "invalid_price")
            continue
        if price <= 0:
            drop(rec, "invalid_price")
            continue

        # --- currency / payment (normalized) ------------------------------
        cur = raw_cur.upper()
        if cur not in FX_TO_USD:
            drop(rec, "unknown_currency")
            continue
        pay = raw_pay.lower()
        if pay not in PAYMENTS:
            drop(rec, "unknown_payment")
            continue

        # --- within-file duplicate (checked last: field errors win) -------
        if oid in seen_ids:
            drop(rec, "duplicate_order_id")
            continue
        seen_ids.add(oid)

        clean.append(CleanRow(oid, dt, store, sku, qty, price, cur, customer, pay))

    return clean, rejected
