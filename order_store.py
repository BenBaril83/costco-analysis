#!/usr/bin/env python3
"""Order storage, kept behind a small interface so a database can replace the JSON file.

Orders live in data/orders.json as {order_number: order}. Each order carries its
header details (date, store, totals, savings), validation result and clean item rows.
To move to a database later, implement the same three methods (get/upsert/all).
"""

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional


@dataclass
class OrderItem:
    item_number: str
    name: str
    category: str
    quantity: int
    price: Decimal
    discount: Decimal
    net_price: Decimal
    tax_code: str
    raw_description: str
    low_confidence: bool
    source: str  # catalog | rule | guess


@dataclass
class Order:
    order_number: str
    order_date: Optional[str]
    store: Optional[str]
    member_number: Optional[str]
    subtotal: Optional[Decimal]
    taxes: Optional[Decimal]
    total: Optional[Decimal]
    instant_savings: Optional[Decimal]
    total_item_count: Optional[int]
    source_file: str
    validated: bool
    mismatches: list = field(default_factory=list)
    items: list = field(default_factory=list)


def _encode(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"not serializable: {type(o)}")


class JsonOrderStore:
    def __init__(self, path="data/orders.json"):
        self.path = Path(path)

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, order_number: str) -> Optional[dict]:
        return self._load().get(order_number)

    def all(self) -> list:
        return list(self._load().values())

    def upsert(self, order: Order):
        data = self._load()
        data[order.order_number] = asdict(order)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, default=_encode))
