"""Tests for the receipt pipeline. Run: uv run python -m unittest test_receipt_pipeline -v

The receipt below is synthetic, built from the line formats in the task description.
"""

import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from order_store import JsonOrderStore
from process_receipt import build_order
from receipt_identify import ItemCatalog
from receipt_parser import parse_receipt, validate

RECEIPT = """\
Costco Wholesale #123 BAYONNE
Order Number 21133401100522303241037
Oct 5, 2025
Member 111892345678
1424970 CASHMERE TP 26.99 2
/1424970 5.50-
2446056 HUGGIES SZ4 42.99 2
/ 2446056 3.00-
1912639 KS PAPER TOWEL 24.99 2
TPD/1912639 2.00-
1111111 DOVE 9.99 2
SHAMPOO
231 BNLS CHICKEN BREAST 40.63 N
1.234 kg @ 32.99/kg
2222222 KS PROTEIN BARS 24.99 B
3333333 QUEST PROTEIN BARS 29.99 B
4444444 FARM GIRL CEREAL 8.99 N
5555555 CHEERIOS 7.99 N
6666666 HN CHEERIOS 7.99 N
7777777 PURFILTRE 2% 4L 8.49 N
8888888 STRAWBERRIES 2LB 7.99 N
https://www.costco.ca/orders 1/1
SUBTOTAL 231.52
TAX 5.10
TOTAL 236.62
INSTANT SAVINGS 10.50
TOTAL NUMBER OF ITEMS SOLD = 12
"""


class PipelineTest(unittest.TestCase):
    def test_parse_and_discounts(self):
        p = parse_receipt(RECEIPT)
        self.assertEqual(len(p.items), 12)
        by_num = {i.item_number: i for i in p.items}
        self.assertEqual(by_num["1424970"].net_price, D("21.49"))
        self.assertEqual(by_num["1912639"].discount, D("2.00"))
        self.assertEqual(by_num["2446056"].net_price, D("39.99"))
        self.assertEqual(by_num["1111111"].description, "DOVE SHAMPOO")
        self.assertEqual(by_num["231"].price, D("40.63"))
        self.assertEqual(p.header.order_number, "21133401100522303241037")
        self.assertEqual(p.header.order_date, "2025-10-05")
        self.assertEqual(validate(p), [])

    def test_wrapped_description_before_price_and_name_discount(self):
        p = parse_receipt("1111111 DOVE\nSHAMPOO 9.99 2\n/ DOVE 1.00-\nSUBTOTAL 8.99\n"
                          "INSTANT SAVINGS 1.00\nTOTAL NUMBER OF ITEMS SOLD 1\n")
        self.assertEqual(p.items[0].description, "DOVE SHAMPOO")
        self.assertEqual(p.items[0].net_price, D("8.99"))
        self.assertEqual(validate(p), [])

    def test_discount_split_across_lines(self):
        p = parse_receipt("1424970 CASHMERE TP 26.99 2\nTPD/1424970\n5.50-\nSUBTOTAL 21.49\n"
                          "INSTANT SAVINGS 5.50\nTOTAL NUMBER OF ITEMS SOLD 1\n")
        self.assertEqual(p.items[0].discount, D("5.50"))

    def test_mismatches_are_surfaced(self):
        bad = RECEIPT.replace("SUBTOTAL 231.52", "SUBTOTAL 230.00").replace("ITEMS SOLD = 12", "ITEMS SOLD = 13")
        checks = [m.check for m in validate(parse_receipt(bad))]
        self.assertIn("sum of net prices == SUBTOTAL", checks)
        self.assertIn("item count == TOTAL NUMBER OF ITEMS SOLD", checks)

    def test_unmatched_discount_is_a_mismatch(self):
        p = parse_receipt(RECEIPT.replace("/1424970 5.50-", "/9999999 5.50-"))
        self.assertTrue(any("parent item" in m.check for m in validate(p)))

    def test_names_categories_and_uniqueness(self):
        with tempfile.TemporaryDirectory() as d:
            order, mism = build_order(RECEIPT, "r.txt", ItemCatalog(Path(d) / "cat.json"))
        self.assertEqual(mism, [])
        names = {i.name: i for i in order.items}
        self.assertEqual(len(names), len(order.items))  # unique
        for expected in ("Toilet Paper", "Diapers", "Paper Towels", "Shampoo", "Chicken", "Kirkland Protein Bars",
                         "Quest Protein Bars", "Farm Girl Cereal", "Cheerios", "Honey Nut Cheerios", "Milk",
                         "Strawberries"):
            self.assertIn(expected, names)
        self.assertEqual(names["Strawberries"].category, "Fruits")
        self.assertEqual(names["Diapers"].category, "Baby")
        self.assertEqual(names["Shampoo"].category, "Health & Personal Care")
        self.assertEqual(names["Quest Protein Bars"].category, "Snacks & Protein")

    def test_unknown_item_is_low_confidence_and_not_learned(self):
        with tempfile.TemporaryDirectory() as d:
            cat = ItemCatalog(Path(d) / "cat.json")
            text = "9999999 ZZQX WIDGET 5.00 2\nSUBTOTAL 5.00\nTOTAL NUMBER OF ITEMS SOLD 1\n"
            order, _ = build_order(text, "r.txt", cat)
            self.assertTrue(order.items[0].low_confidence)
            self.assertNotIn("9999999", cat.entries)

    def test_catalog_grows_and_wins_next_time(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cat.json"
            cat = ItemCatalog(path)
            build_order(RECEIPT, "r.txt", cat)
            cat.save()
            cat2 = ItemCatalog(path)
            self.assertIn("1424970", cat2.entries)
            order, _ = build_order(RECEIPT, "r.txt", cat2)
            self.assertTrue(all(i.source == "catalog" for i in order.items))

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            order, _ = build_order(RECEIPT, "r.txt", ItemCatalog(Path(d) / "cat.json"))
            store = JsonOrderStore(Path(d) / "orders.json")
            store.upsert(order)
            got = store.get("21133401100522303241037")
            self.assertEqual(got["subtotal"], "231.52")
            self.assertEqual(len(got["items"]), 12)


if __name__ == "__main__":
    unittest.main()
