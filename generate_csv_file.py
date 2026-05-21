#!/usr/bin/env python3
"""Export Costco receipt JSON data to CSV files using DuckDB.

Emits two CSVs at the repo root:
  - costco-items.csv     line-item level
  - costco-receipts.csv  receipt-level totals
"""

from pathlib import Path

import duckdb

ITEMS_QUERY = """
WITH receipts AS (
    SELECT json_extract(data, '$.receiptsWithCounts.receipts[0]') AS r
    FROM read_json_auto('data/receipts/*.json')
)
SELECT
    r ->> 'transactionDate'                       AS transaction_date,
    r ->> 'transactionBarcode'                    AS transaction_barcode,
    r ->> 'warehouseName'                         AS warehouse_name,
    r ->> 'transactionType'                       AS transaction_type,
    item ->> 'itemNumber'                         AS item_number,
    item ->> 'itemDescription01'                  AS description,
    item ->> 'itemDescription02'                  AS description2,
    description || ' ' || description2            AS combined_description,
    (item ->> 'itemDepartmentNumber')::INTEGER    AS item_department_number,
    (item ->> 'itemUnitPriceAmount')::DOUBLE      AS item_unit_price,
    (item ->> 'amount')::DOUBLE                   AS item_amount,
    (item ->> 'unit')::DOUBLE                     AS item_quantity
FROM receipts,
        UNNEST(json_extract(r, '$.itemArray[*]')) AS t(item)
"""

RECEIPTS_QUERY = """
WITH receipts AS (
    SELECT json_extract(data, '$.receiptsWithCounts.receipts[0]') AS r
    FROM read_json_auto('data/receipts/*.json')
)
SELECT
    r ->> 'transactionDate'              AS transaction_date,
    r ->> 'transactionBarcode'           AS transaction_barcode,
    r ->> 'warehouseName'                AS warehouse_name,
    r ->> 'transactionType'              AS transaction_type,
    (r ->> 'subTotal')::DOUBLE           AS subtotal,
    (r ->> 'taxes')::DOUBLE              AS taxes,
    (r ->> 'total')::DOUBLE              AS total,
    (r ->> 'instantSavings')::DOUBLE     AS instant_savings,
    (r ->> 'totalItemCount')::INTEGER    AS total_item_count
FROM receipts
"""


def export(conn, query, output_path):
    conn.execute(f"COPY ({query}) TO '{output_path}' (HEADER, DELIMITER ',')")
    rows = conn.execute(f"SELECT COUNT(*) FROM ({query}) AS s").fetchone()[0]
    print(f"  wrote {rows:,} rows → {output_path}")


def generate_csv_file():
    project_root = Path(__file__).parent
    data_dir = project_root / "data" / "receipts"

    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")
    json_files = list(data_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")
    print(f"Found {len(json_files)} receipt files")

    conn = duckdb.connect()
    try:
        export(conn, ITEMS_QUERY, project_root / "costco-items.csv")
        export(conn, RECEIPTS_QUERY, project_root / "costco-receipts.csv")
    finally:
        conn.close()


if __name__ == "__main__":
    generate_csv_file()
