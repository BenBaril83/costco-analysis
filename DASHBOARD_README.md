# Costco Items Analysis Dashboard

A beautiful, interactive HTML dashboard for analyzing your Costco purchase data with price trends and statistics.

## Features

🛒 **Interactive Visualization**

- Beautiful ECharts-powered line charts showing price trends over time
- Multi-select item filtering with search functionality
- Responsive design that works on desktop and mobile

📊 **Comprehensive Statistics**

- Min, Max, Average, Median, and Standard Deviation for each item
- Real-time statistics updates based on your selection
- Color-coded statistics cards in the sidebar

📋 **Data Table**

- Sortable table showing underlying transaction data
- Displays transaction date, item name, description, and price
- Limited to 100 rows for optimal performance

🎨 **Modern UI**

- Glass-morphism design with gradient backgrounds
- Smooth animations and hover effects
- Professional color scheme

## How to Use

1. **Open the Dashboard**

   ```bash
   # Serve the files using Python's built-in server
   python -m http.server 8000

   # Or use any other local server
   # Then open: http://localhost:8000/costco-dashboard.html
   ```

2. **Select Items**

   - Use the multi-select dropdown in the sidebar
   - Search for specific items using the search box
   - Use "Select All" or "Clear All" buttons for bulk operations

3. **Analyze Data**

   - View price trends in the main chart
   - Check statistics in the sidebar for selected items
   - Browse underlying data in the table below the chart

4. **Chart Interactions**
   - Zoom in/out using mouse wheel or zoom controls
   - Hover over data points for detailed tooltips
   - Save chart as image using the toolbar

## Default Behavior

- By default, shows average price trends for all items
- Y-axis represents unit price in dollars
- X-axis shows transaction dates
- Statistics show aggregated data for all selected items

## Data Format

The dashboard loads two CSVs from the same directory; both are produced by `generate_csv_file.py`.

`costco-items.csv` (one row per line item):

- `transaction_date` — purchase date, `YYYY-MM-DD`
- `transaction_barcode` — receipt barcode
- `warehouse_name` — store name
- `transaction_type` — `Sales`, `Returns`, etc.
- `item_number` — stable item identifier; used for grouping
- `description`, `description2`, `combined_description` — display text
- `item_department_number` — Costco department number
- `item_unit_price` — per-unit price in dollars
- `item_amount` — line-item paid amount
- `item_quantity` — units on this line

`costco-receipts.csv` (one row per receipt):

- `transaction_date`, `transaction_barcode`, `warehouse_name`, `transaction_type`
- `subtotal`, `taxes`, `total`, `instant_savings`, `total_item_count`

## Tabs

- **Item Trends** — line chart + data table for selected items, grouped by `item_number`.
- **Price Index** — personal Costco price index built from items bought ≥4 times. Each item is normalized to 100 at its baseline (avg of first 2 purchases); the chart plots the monthly mean across qualified items. Headline cards show total %, annualized %, and item count. Inflation = red, deflation = green.
- **Departments** — stacked monthly spend across the top 10 departments by lifetime spend, plus a lifetime-spend table.

## Browser Compatibility

- Modern browsers (Chrome, Firefox, Safari, Edge)
- Requires JavaScript enabled
- Works best with internet connection for CDN resources

## Customization

You can customize the dashboard by:

- Modifying colors in the CSS variables
- Adjusting chart options in the `setupChart()` function
- Changing the number of displayed table rows
- Adding new statistical calculations

Enjoy analyzing your Costco shopping patterns! 🛒📈
