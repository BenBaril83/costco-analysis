#!/usr/bin/env python3
"""Turn Costco Canada receipts (PDF or extracted text) into a clean, categorized order.

    uv run python process_receipt.py receipt.txt [more.pdf ...]
        [--orders data/orders.json] [--catalog data/item_catalog.json] [--save-invalid]

Pipeline: parse lines → apply discounts → identify → simplify names → categorize → validate.
Validation failures are printed and the order is NOT stored unless --save-invalid is given.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from order_store import JsonOrderStore, Order, OrderItem
from receipt_identify import ItemCatalog, identify, resolve_names
from receipt_parser import parse_receipt, read_receipt_text, validate


def build_order(text: str, source_file: str, catalog: ItemCatalog):
    parsed = parse_receipt(text)
    mismatches = validate(parsed)  # on raw lines, before same-item rows are merged

    # Same item bought twice → one row with a quantity, so names stay unique.
    merged = {}
    for raw in parsed.items:
        row = merged.setdefault(raw.item_number, {"raw": raw, "qty": 0, "price": Decimal("0.00"), "disc": Decimal("0.00")})
        row["qty"] += 1
        row["price"] += raw.price
        row["disc"] += raw.discount

    idents = resolve_names([identify(n, r["raw"].description, r["raw"].tax_code, catalog)
                            for n, r in merged.items()])
    items = [OrderItem(i.item_number, i.name, i.category, r["qty"], r["price"], r["disc"], r["price"] - r["disc"],
                       r["raw"].tax_code, r["raw"].description, i.low_confidence, i.source)
             for i, r in zip(idents, merged.values())]
    for i in idents:
        catalog.learn(i)

    h = parsed.header
    order = Order(h.order_number or Path(source_file).stem, h.order_date, h.store, h.member_number,
                  h.subtotal, h.taxes, h.total, h.instant_savings, h.total_item_count, source_file,
                  not mismatches, [str(m) for m in mismatches], items)
    return order, mismatches


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--orders", default="data/orders.json")
    ap.add_argument("--catalog", default="data/item_catalog.json")
    ap.add_argument("--save-invalid", action="store_true", help="store orders even if validation fails")
    args = ap.parse_args(argv)

    store, catalog, failed = JsonOrderStore(args.orders), ItemCatalog(args.catalog), 0
    for f in args.files:
        order, mismatches = build_order(read_receipt_text(f), f, catalog)
        print(f"\n{f}: order {order.order_number}  {order.order_date}  {order.store}  total {order.total}")
        for it in order.items:
            flag = "  ?low-confidence" if it.low_confidence else ""
            print(f"  {it.name:<32} {it.category:<24} x{it.quantity} {it.net_price:>8}{flag}")
        if mismatches:
            failed += 1
            print("  VALIDATION FAILED:")
            for m in mismatches:
                print(f"    - {m}")
        if not mismatches or args.save_invalid:
            store.upsert(order)
            print(f"  stored in {args.orders}" + ("" if not mismatches else " (flagged invalid)"))
        else:
            print("  NOT stored (use --save-invalid to keep it)")
    catalog.save()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
