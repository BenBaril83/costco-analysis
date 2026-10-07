#!/usr/bin/env python3
"""Parse Costco Canada receipt text into raw lines, apply discounts, validate.

Stages 1, 2 and 6 of the receipt pipeline (see process_receipt.py for the
whole thing). Pure stdlib; money is handled as Decimal.
"""

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

CENT = Decimal("0.01")

# <item#> <DESCRIPTION> <price> <tax code>; an optional leading "E " flag is allowed.
ITEM_RE = re.compile(
    r"^(?:[A-Z]\s+)?(?P<num>\d{2,8})\s+(?P<desc>.+?)\s+(?P<price>\d{1,5}\.\d{2})\s+(?P<tax>[A-Z0-9])$")
# Item whose description wraps before the price: "1234567 DOVE"
ITEM_START_RE = re.compile(r"^(?:[A-Z]\s+)?(?P<num>\d{2,8})\s+(?P<desc>[A-Z][^\d]*?)$")
# Second line of a wrapped item: "SHAMPOO 9.99 2"
ITEM_TAIL_RE = re.compile(r"^(?P<desc>.+?)\s+(?P<price>\d{1,5}\.\d{2})\s+(?P<tax>[A-Z0-9])$")
# "TPD/1912639 5.50-", "/ 2446056 5.50-", "/ HUGGIES 3.00-"
DISCOUNT_RE = re.compile(
    r"^(?P<tag>[A-Z]{0,4})\s*/\s*(?P<ref>\S.*?)\s*(?P<amt>\d+\.\d{2})-$")
DISCOUNT_REF_ONLY_RE = re.compile(r"^(?P<tag>[A-Z]{0,4})\s*/\s*(?P<ref>\S.*?)$")
AMOUNT_ONLY_RE = re.compile(r"^(?P<amt>\d+\.\d{2})-$")
CONTINUATION_RE = re.compile(r"^[A-Z][A-Z0-9 &'./%-]*$")
WEIGHT_RE = re.compile(r"\b(kg|lb)\b|@", re.I)

SUBTOTAL_RE = re.compile(r"^SUB\s*TOTAL\s*\$?\s*(?P<v>-?\d[\d,]*\.\d{2})", re.I)
SAVINGS_RE = re.compile(r"INSTANT\s+SAVINGS\D*(?P<v>\d[\d,]*\.\d{2})", re.I)
COUNT_RE = re.compile(r"TOTAL\s+NUMBER\s+OF\s+ITEMS\s+SOLD\D*(?P<v>\d+)", re.I)
TAX_RE = re.compile(r"^(?:TOTAL\s+)?TAX\s*\$?\s*(?P<v>\d[\d,]*\.\d{2})$", re.I)
TOTAL_RE = re.compile(r"^TOTAL\s*\$?\s*(?P<v>\d[\d,]*\.\d{2})$", re.I)
FOOTER_START_RE = SUBTOTAL_RE

# Page chrome from PDF printouts of costco.ca "Orders & Purchases".
IGNORE_RE = re.compile(
    r"^(https?://|www\.|page\s+\d+|\d+\s*/\s*\d+$|\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}|\d{1,2}:\d{2}\s*[AP]M)",
    re.I)

BARCODE_RE = re.compile(r"\b(\d{20,})\b")
ORDER_NO_RE = re.compile(r"(?:order|invoice|transaction)\s*(?:number|no\.?|#)\s*:?\s*(\d{6,})", re.I)
MEMBER_RE = re.compile(r"member(?:ship)?\s*(?:number|no\.?|#)?\s*:?\s*(\d{8,})", re.I)
STORE_RE = re.compile(r"(?:costco\s+wholesale|warehouse)\s*#?\s*(?P<num>\d+)?\s*[-,:]?\s*(?P<name>[A-Za-z][A-Za-z .'-]*)?", re.I)
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y")
DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z][a-z]{2,8}\.? \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]{2,8} \d{4})")


def money(s) -> Decimal:
    return Decimal(str(s).replace(",", "")).quantize(CENT)


@dataclass
class RawItem:
    item_number: str
    description: str
    price: Decimal
    tax_code: str
    discount: Decimal = Decimal("0.00")
    discount_lines: list = field(default_factory=list)  # raw text of attached discount lines
    note: str = ""  # e.g. weight line "1.234 kg @ 32.99/kg"

    @property
    def net_price(self) -> Decimal:
        return self.price - self.discount


@dataclass
class ReceiptHeader:
    order_number: Optional[str] = None
    order_date: Optional[str] = None  # ISO yyyy-mm-dd
    store: Optional[str] = None
    member_number: Optional[str] = None
    subtotal: Optional[Decimal] = None
    taxes: Optional[Decimal] = None
    total: Optional[Decimal] = None
    instant_savings: Optional[Decimal] = None
    total_item_count: Optional[int] = None


@dataclass
class ParsedReceipt:
    header: ReceiptHeader
    items: list
    unmatched_discounts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class Mismatch:
    check: str
    expected: object
    actual: object

    def __str__(self):
        return f"{self.check}: receipt says {self.expected}, computed {self.actual}"


def read_receipt_text(path) -> str:
    """Read a receipt from .txt, or .pdf via the poppler `pdftotext` binary."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        try:
            out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                 capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise RuntimeError("PDF input needs the `pdftotext` binary (poppler-utils), "
                               "or pass an already-extracted .txt file.")
        return out.stdout
    return path.read_text()


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def parse_header_line(line: str, h: ReceiptHeader):
    """Best-effort metadata extraction from a pre-item line."""
    if h.order_number is None:
        m = BARCODE_RE.search(line) or ORDER_NO_RE.search(line)
        if m:
            h.order_number = m.group(1)
    if h.member_number is None and (m := MEMBER_RE.search(line)):
        h.member_number = m.group(1)
    if h.order_date is None and (m := DATE_RE.search(line)):
        raw = m.group(1).replace(".", "")
        for fmt in DATE_FORMATS:
            try:
                h.order_date = datetime.strptime(raw, fmt).date().isoformat()
                break
            except ValueError:
                pass
    if h.store is None and (m := STORE_RE.search(line)):
        parts = [p for p in (m.group("num"), (m.group("name") or "").strip()) if p]
        label = " ".join(parts)
        if label:
            h.store = label if m.group("num") is None else f"#{m.group('num')} {(m.group('name') or '').strip()}".strip()


def _find_parent(items, ref: str):
    """Locate the item a discount refers to (by number, else by name); latest preceding wins."""
    ref_u = ref.strip().upper()
    if re.fullmatch(r"\d+", ref_u):
        for it in reversed(items):
            if it.item_number == ref_u:
                return it
        return None
    for it in reversed(items):
        if ref_u in it.description.upper():
            return it
    return None


def parse_receipt(text: str) -> ParsedReceipt:
    header = ReceiptHeader()
    items: list[RawItem] = []
    unmatched: list[str] = []
    warnings: list[str] = []
    pending_item = None      # (num, desc) awaiting its price line
    pending_discount = None  # raw discount line awaiting its amount line
    last_was_item = False
    in_footer = False

    def attach(raw_line, ref, amt):
        parent = _find_parent(items, ref)
        if parent is None:
            unmatched.append(raw_line)
            return
        parent.discount += money(amt)
        parent.discount_lines.append(raw_line)

    for raw in text.splitlines():
        line = _clean(raw)
        if not line:
            continue
        if not in_footer and not items and pending_item is None:
            parse_header_line(line, header)
        if IGNORE_RE.match(line):
            continue

        # Footer: totals and the cross-check figures.
        if in_footer or FOOTER_START_RE.match(line):
            in_footer = True
            if m := SUBTOTAL_RE.match(line):
                header.subtotal = money(m.group("v"))
            elif m := SAVINGS_RE.search(line):
                header.instant_savings = money(m.group("v"))
            elif m := COUNT_RE.search(line):
                header.total_item_count = int(m.group("v"))
            elif m := TAX_RE.match(line):
                header.taxes = (header.taxes or Decimal("0.00")) + money(m.group("v"))
            elif m := TOTAL_RE.match(line):
                header.total = money(m.group("v"))
            continue

        if pending_discount:
            if m := AMOUNT_ONLY_RE.match(line):
                tag, ref = pending_discount
                attach(f"{tag}/{ref} {line}", ref, m.group("amt"))
                pending_discount = None
                continue
            warnings.append(f"discount reference without amount: {pending_discount[1]}")
            pending_discount = None

        if m := DISCOUNT_RE.match(line):
            attach(line, m.group("ref"), m.group("amt"))
            last_was_item = False
            continue

        if pending_item:
            num, desc = pending_item
            pending_item = None
            if m := ITEM_TAIL_RE.match(line):
                items.append(RawItem(num, f"{desc} {m.group('desc')}", money(m.group("price")), m.group("tax")))
                last_was_item = True
                continue
            if items:  # before the first item this is just a header line (e.g. a street address)
                warnings.append(f"item {num} '{desc}' never got a price line")

        if m := ITEM_RE.match(line):
            items.append(RawItem(m.group("num"), m.group("desc"), money(m.group("price")), m.group("tax")))
            last_was_item = True
            continue

        if items and (m := DISCOUNT_REF_ONLY_RE.match(line)) and line.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ ").startswith("/"):
            pending_discount = (m.group("tag"), m.group("ref"))
            last_was_item = False
            continue

        if items and last_was_item and WEIGHT_RE.search(line):
            items[-1].note = line
            continue

        if items and last_was_item and CONTINUATION_RE.match(line):
            items[-1].description += f" {line}"  # wrapped description on the next line
            continue

        if m := ITEM_START_RE.match(line):
            pending_item = (m.group("num"), m.group("desc"))
            last_was_item = False
            continue

        last_was_item = False  # anything else is header/footer noise

    if pending_discount:
        warnings.append(f"discount reference without amount: {pending_discount[1]}")
    return ParsedReceipt(header, items, unmatched, warnings)


def validate(parsed: ParsedReceipt) -> list:
    """Cross-check parsed items against the receipt's own totals."""
    h, bad = parsed.header, []
    net = sum((i.net_price for i in parsed.items), Decimal("0.00"))
    disc = sum((i.discount for i in parsed.items), Decimal("0.00"))
    if h.subtotal is None:
        bad.append(Mismatch("SUBTOTAL present", "a SUBTOTAL line", "not found"))
    elif net != h.subtotal:
        bad.append(Mismatch("sum of net prices == SUBTOTAL", h.subtotal, net))
    expected_disc = h.instant_savings if h.instant_savings is not None else Decimal("0.00")
    if disc != expected_disc:
        bad.append(Mismatch("sum of discounts == INSTANT SAVINGS", expected_disc, disc))
    if h.total_item_count is None:
        bad.append(Mismatch("TOTAL NUMBER OF ITEMS SOLD present", "a count line", "not found"))
    elif len(parsed.items) != h.total_item_count:
        bad.append(Mismatch("item count == TOTAL NUMBER OF ITEMS SOLD", h.total_item_count, len(parsed.items)))
    for line in parsed.unmatched_discounts:
        bad.append(Mismatch("discount has a parent item", line, "no matching item"))
    for w in parsed.warnings:
        bad.append(Mismatch("parse warning", "clean parse", w))
    return bad
