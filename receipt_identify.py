#!/usr/bin/env python3
"""Identify, simplify and categorize parsed receipt items (pipeline stages 3-5).

Identification order:
  1. local catalog (data/item_catalog.json, keyed by item number; grows over time)
  2. keyword rules on the abbreviated description (RULES below)
  3. a low-confidence guess from the tax code
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

CATEGORIES = [
    "Meat & Fish", "Snacks & Protein", "Pantry & Breakfast", "Vegetables", "Fruits",
    "Dairy", "Bakery", "Frozen Foods", "Baby", "Household & Paper",
    "Health & Personal Care", "Clothing", "Flowers",
]
FOOD_CATEGORIES = {"Meat & Fish", "Pantry & Breakfast", "Vegetables", "Fruits", "Dairy", "Bakery", "Frozen Foods"}
# Snacks, flowers and non-food are taxable; basic groceries are zero-rated (N).
TAXABLE_CATEGORIES = set(CATEGORIES) - FOOD_CATEGORIES

# Abbreviations expanded for display / matching.
ABBREVIATIONS = {
    "KS": "Kirkland Signature", "HN": "Honey Nut", "BNLS": "Boneless", "SKNLS": "Skinless",
    "ORG": "Organic", "FT": "Fair Trade", "PURFILTRE": "Natrel PurFiltre Milk",
    "TP": "Toilet Paper", "PT": "Paper Towels",
}
PROTEIN_CONTEXT = re.compile(r"\b(BAR|BARS|SHAKE|POWDER|WHEY|CHOC|VANILLA|COOKIE|CRISP)\b")

BRANDS = {  # token (upper) -> display brand
    "KS": "Kirkland", "KIRKLAND": "Kirkland", "QUEST": "Quest", "DOVE": "Dove", "HUGGIES": "Huggies",
    "PAMPERS": "Pampers", "CASHMERE": "Cashmere", "FARM": "Farm Girl", "NATREL": "Natrel",
    "PURFILTRE": "Natrel", "CHEERIOS": "Cheerios", "NATURE": "Nature Valley", "KIND": "Kind",
    "CLIF": "Clif", "BOUNTY": "Bounty", "KLEENEX": "Kleenex", "TIDE": "Tide", "OIKOS": "Oikos",
}

# (regex on upper-case description, generic name, category, vague?)
# vague=True: the generic name alone is too unspecific, so the brand is kept.
RULES = [
    (r"HONEY NUT CHEERIOS|\bHN CHEERIOS", "Honey Nut Cheerios", "Pantry & Breakfast", False),
    (r"CHEERIOS", "Cheerios", "Pantry & Breakfast", False),
    (r"CEREAL|GRANOLA|MUESLI", "Cereal", "Pantry & Breakfast", True),
    (r"OATMEAL|OATS|PANCAKE|SYRUP|PEANUT BUTTER|\bJAM\b|\bHONEY\b|COFFEE|\bTEA\b|PASTA|\bRICE\b|\bOIL\b|OLIVE|FLOUR|SUGAR|SAUCE|SOUP|NUTS?\b|ALMOND", "Pantry Item", "Pantry & Breakfast", True),
    (r"PROTEIN BAR|PRTN BAR|\bBARS?\b", "Protein Bars", "Snacks & Protein", True),
    (r"PROTEIN SHAKE|PRTN SHAKE|WHEY|PROTEIN POWDER", "Protein Shake", "Snacks & Protein", True),
    (r"CHIPS|CRACKERS|POPCORN|PRETZEL|COOKIES?\b|CANDY|CHOC|JERKY|TRAIL MIX", "Snacks", "Snacks & Protein", True),
    (r"BEEF|STEAK|BRISKET|\bRIB\b", "Beef", "Meat & Fish", False),
    (r"CHICKEN|BNLS.*BREAST|THIGH|WINGS", "Chicken", "Meat & Fish", False),
    (r"PORK|BACON|SAUSAGE|\bHAM\b", "Pork", "Meat & Fish", True),
    (r"SALMON|TUNA|SHRIMP|FISH|TILAPIA|COD\b", "Fish", "Meat & Fish", True),
    (r"STRAWBERR", "Strawberries", "Fruits", False),
    (r"BLUEBERR", "Blueberries", "Fruits", False),
    (r"RASPBERR", "Raspberries", "Fruits", False),
    (r"MANDARIN|CLEMENTINE", "Mandarins", "Fruits", False),
    (r"BANANA", "Bananas", "Fruits", False),
    (r"APPLE", "Apples", "Fruits", False),
    (r"GRAPE", "Grapes", "Fruits", False),
    (r"AVOCADO", "Avocados", "Fruits", False),
    (r"CUCUMBER", "Cucumbers", "Vegetables", False),
    (r"TOMATO", "Tomatoes", "Vegetables", False),
    (r"CARROT", "Carrots", "Vegetables", False),
    (r"BROCCOLI", "Broccoli", "Vegetables", False),
    (r"SPINACH|LETTUCE|SALAD|KALE", "Salad Greens", "Vegetables", False),
    (r"POTATO", "Potatoes", "Vegetables", False),
    (r"PEPPER", "Peppers", "Vegetables", False),
    (r"ONION", "Onions", "Vegetables", False),
    (r"PURFILTRE|\bMILK\b", "Milk", "Dairy", False),
    (r"YOGURT|OIKOS|GREEK", "Yogurt", "Dairy", False),
    (r"CHEESE|CHEDDAR|MOZZ", "Cheese", "Dairy", False),
    (r"BUTTER\b", "Butter", "Dairy", False),
    (r"EGGS?\b", "Eggs", "Dairy", False),
    (r"BREAD|BAGEL|BUN\b|BUNS\b|MUFFIN|CROISSANT|TORTILLA|PITA", "Bread", "Bakery", True),
    (r"CAKE|PIE\b|DONUT|PASTRY", "Pastry", "Bakery", True),
    (r"FROZEN|\bFRZ\b|PIZZA|ICE CREAM|FRIES", "Frozen Food", "Frozen Foods", True),
    (r"DIAPER|HUGGIES|PAMPERS|WIPES", "Diapers", "Baby", False),
    (r"FORMULA|BABY", "Baby Food", "Baby", True),
    (r"CASHMERE|\bTP\b|TOILET|BATH TISSUE", "Toilet Paper", "Household & Paper", False),
    (r"PAPER TOWEL|\bPT\b|BOUNTY|VIVA", "Paper Towels", "Household & Paper", False),
    (r"KLEENEX|FACIAL TISSUE", "Facial Tissue", "Household & Paper", False),
    (r"DETERGENT|TIDE\b|LAUNDRY|DISH|SOAP.*DISH|SPNG|SPONGE", "Cleaning Supplies", "Household & Paper", True),
    (r"GARBAGE|TRASH|FOIL|ZIPLOC|WRAP\b|BAGS?\b|BATTER", "Household Supplies", "Household & Paper", True),
    (r"SHAMPOO", "Shampoo", "Health & Personal Care", False),
    (r"CONDITIONER", "Conditioner", "Health & Personal Care", False),
    (r"TOOTH|FLOSS|MOUTHWASH", "Dental Care", "Health & Personal Care", True),
    (r"VITAMIN|OMEGA|FISH OIL|PROBIOTIC|IBUPROFEN|ACETAMINOPHEN|ALLERG", "Vitamins & Medicine", "Health & Personal Care", True),
    (r"DEODORANT|LOTION|SUNSCREEN|BODY WASH|SOAP|RAZOR", "Personal Care", "Health & Personal Care", True),
    (r"SOCKS|SHIRT|JACKET|PANTS|JEANS|SWEATER|HOODIE|SHORTS|SLIPPERS|GLOVES", "Clothing", "Clothing", True),
    (r"FLOWER|BOUQUET|ROSES?\b|TULIP|ORCHID|PLANT", "Flowers", "Flowers", False),
]
COMPILED_RULES = [(re.compile(p), n, c, v) for p, n, c, v in RULES]


@dataclass
class Identified:
    item_number: str
    name: str                 # simplified, unique per receipt after resolve_names()
    generic_name: str
    brand: str
    category: str
    expanded_description: str
    source: str               # "catalog" | "rule" | "guess"
    low_confidence: bool
    reason: str = ""


class ItemCatalog:
    """Local item-number lookup table that grows as items get identified."""

    def __init__(self, path="data/item_catalog.json"):
        self.path = Path(path)
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.dirty = False

    def get(self, item_number):
        return self.entries.get(item_number)

    def learn(self, ident: Identified):
        if ident.source == "guess" or ident.item_number in self.entries:
            return
        self.entries[ident.item_number] = {
            "generic_name": ident.generic_name, "brand": ident.brand, "category": ident.category,
            "low_confidence": ident.low_confidence, "learned_from": ident.expanded_description,
        }
        self.dirty = True

    def save(self):
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=2, sort_keys=True))
            self.dirty = False


def expand(description: str) -> str:
    """Expand receipt abbreviations; PRTN reads as Protein in bar/shake context, else Portion."""
    up = description.upper()
    out = []
    for tok in up.split():
        if tok == "PRTN":
            out.append("Protein" if PROTEIN_CONTEXT.search(up) else "Portion")
        elif tok in ABBREVIATIONS and tok not in ("TP", "PT"):  # TP/PT only matter to the rules
            out.append(ABBREVIATIONS[tok])
        else:
            out.append(tok.title() if len(tok) > 3 else tok)
    return " ".join(out)


def find_brand(description: str) -> str:
    for tok in re.findall(r"[A-Z]+", description.upper()):
        if tok in BRANDS:
            return BRANDS[tok]
    return ""


def identify(item_number: str, description: str, tax_code: str, catalog: ItemCatalog = None) -> Identified:
    expanded = expand(description)
    brand = find_brand(description)

    if catalog and (hit := catalog.get(item_number)):
        return Identified(item_number, hit["generic_name"], hit["generic_name"], hit.get("brand", brand),
                          hit["category"], expanded, "catalog", hit.get("low_confidence", False),
                          "item number found in local catalog")

    up = description.upper()
    for rx, name, cat, vague in COMPILED_RULES:
        if rx.search(up):
            # Tax code is a sanity check: a zero-rated (N) line can't be a taxable category.
            # The reverse isn't flagged: snacks/prepared food are taxable, so B/2 on food is plausible.
            conflict = tax_code == "N" and cat in TAXABLE_CATEGORIES
            return Identified(item_number, name, name, brand, cat, expanded, "rule", conflict,
                              f"matched /{rx.pattern[:30]}/" + ("; tax code disagrees" if conflict else ""))

    # Fallback: guess from the tax code, name from the expanded description.
    cat = "Pantry & Breakfast" if tax_code == "N" else "Household & Paper"
    return Identified(item_number, expanded, expanded, brand, cat, expanded, "guess", True,
                      f"no rule matched; category guessed from tax code {tax_code}")


def _vague(ident: Identified) -> bool:
    return any(rx.search(ident.expanded_description.upper()) and v
               for rx, n, c, v in COMPILED_RULES if n == ident.generic_name)


def resolve_names(idents: list) -> list:
    """Stage 4: short generic names; brand/distinguisher only when vague or colliding."""
    for i in idents:
        i.name = i.generic_name
        if i.source != "guess" and i.brand and _vague(i) and not i.generic_name.startswith(i.brand):
            i.name = f"{i.brand} {i.generic_name}"

    def group():
        g = {}
        for i in idents:
            g.setdefault(i.name.lower(), []).append(i)
        return [v for v in g.values() if len(v) > 1]

    # Collisions: add brand, then leftover distinguishing words, then item number.
    for dupes in group():
        for i in dupes:
            if i.brand and not i.name.startswith(i.brand):
                i.name = f"{i.brand} {i.name}"
    for dupes in group():
        for i in dupes:
            words = [w for w in i.expanded_description.split()
                     if w.lower() not in i.name.lower() and not re.fullmatch(r"[\d./-]+\w*", w) and len(w) > 2]
            if words:
                i.name = f"{i.name} ({' '.join(words[:2])})"
    for dupes in group():
        for i in dupes:
            i.name = f"{i.name} #{i.item_number}"
    return idents
