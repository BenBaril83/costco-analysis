# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Install deps and run scripts via `uv` (Python >=3.11):

```bash
uv sync                              # install dependencies
uv run python fetch_receipts.py             # fetch quarterly receipt lists into data/
uv run python fetch_all_receipt_details.py  # fetch per-receipt details into data/receipts/
uv run python generate_csv_file.py          # flatten data/receipts/*.json → costco-items.csv
python -m http.server 8000                  # then open http://localhost:8000/index.html
```

There is no test suite or linter configured.

## Architecture

Three-stage data pipeline; each stage's output is the next stage's input on disk, so stages can be re-run independently.

1. **List fetch** (`fetch_receipts.py`) — calls Costco's `receiptsWithCounts` GraphQL endpoint in quarterly windows from 2020-01-01 to today. Each quarter is saved as `data/costco_data_<start>_to_<end>.json`. Only summary fields (incl. `transactionBarcode`) come back at this stage.

2. **Detail fetch** (`fetch_all_receipt_details.py` → `fetch_receipt_details.py`) — scans `data/costco_data_*.json` for every `transactionBarcode`, then calls the same GraphQL endpoint with a barcode-scoped query to pull full item-level data. Each receipt is saved as `data/receipts/costco_data_receipt_<barcode>.json`. The batch script skips barcodes that already have a receipt file on disk, so it's safe to re-run. `fetch_all_receipt_details.py` loads `fetch_receipt_details.py` via `importlib.util.spec_from_file_location` (not a package import) — the file must stay at repo root.

3. **CSV export** (`generate_csv_file.py`) — uses DuckDB's `read_json_auto('data/receipts/*.json')` to write two CSVs at repo root: `costco-items.csv` (one row per line item, unnested from `itemArray`, includes department + paid amount) and `costco-receipts.csv` (one row per receipt with subtotal / taxes / total / instant savings). Both queries live as `ITEMS_QUERY` / `RECEIPTS_QUERY` module constants. `index.html` (a self-contained ECharts dashboard, no build step) fetches both via same-origin requests and renders three tabs: Item Trends, Price Index (personal CPI keyed on `item_number`), Departments (top-10 monthly stacked spend).

## Auth

All API calls require three env vars (`COSTCO_BEARER_TOKEN`, `COSTCO_CLIENT_ID`, `COSTCO_CLIENT_IDENTIFIER`) loaded from `.env` via `python-dotenv`. These are not obtainable programmatically — the user logs in to costco.com manually and copies them from the GraphQL request headers in browser devtools. The bearer token expires; refresh it when fetches start returning 401/403.

The endpoint, headers, and the `costco.service` / `costco.env` / `costco-x-authorization` / `costco-x-wcs-clientId` / `client-identifier` header shape are duplicated between `fetch_receipts.py` and `fetch_receipt_details.py` — keep them in sync.
