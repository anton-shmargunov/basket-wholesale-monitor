# Basket-Wholesale Monitor (BWM)

Local Streamlit app for Basket-Wholesale Monitor. It keeps a DuckDB file on this machine and does not upload the quant report or the database password to GitHub.

## Run

From this folder, with Python 3.9:

```text
pip install -r requirements.txt
streamlit run app.py
```

Open the Data page and load a tracking basket export (`.xlsx` or `.csv`). The sample file next to this project is filled in as the default path when it is present.

Loaded tables live in `data/bskuw.duckdb`. That file is gitignored.

## What each source contributes

Tracking basket report, columns `year_week`, `basket`, `product BS`, `SKU`, `StockQty_W`, and `grade` when the file has it. Grade is `A` or `B`. One SKU can have both. Reloading a file replaces every week that file contains. Rows whose SKU does not start with `SKU` are dropped. `StockQty_W` is a weekly snapshot: the Basket SKUs page sums it across baskets for the one week you select, and across grades unless Grade is set.

Quant CSV supplies both the SKU attribute table and wholesale sales. Give a file path. The file is about 2 GB, so it is not sent through the browser upload. SKU attributes kept are `SKU`, `Internal Category`, `Product Name`, `Condition`, `Brand`, `Model`, `Size`, `Section`, `Aspect`, `Rim`, `Tread`, `Majority`, one row per SKU. If several quant rows share a SKU, the most common value of each attribute is kept.

A wholesale sale is one tire whose `Location` is `Physical Locations / FRD / Utilisation Scrap`. Each sale keeps its `Majority`. Grade A counts `No Repair` and `Minor Repair`. Grade B counts `Major Repair` and `Close to Sidewall`. A blank sales order date or number does not exclude it. Reload the quant file after this change so Majority is stored on each sale. Loading a quant file replaces the wholesale table and stores the latest `Incoming date to saleable location` in the whole file, including rows that are not wholesale. A time may include fractional seconds, such as `2021-11-02 21:19:18.443852`. The Basket SKUs page and the Wholesale page both count wholesale tires and filter that date. An empty start date means no lower bound, and an empty end date means no upper bound. The preset list is empty, last week, last month, and last year. Those three end on that latest incoming date and cover 7, 30, and 365 days. SKU, Brand, Size, Section, Aspect, and Rim match the whole value. Name matches any part of the name. A sale counts for a basket when its SKU is in that basket in the selected tracking week. Filters stay filled when you switch pages.

MySQL table `clear_data.clear_sku`: `sku`, `name`, `brand`, `model`, `size`, `tread`, `condition`. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in host, port, user, password, and database. `secrets.toml` is gitignored. Internal category and majority stay empty for a MySQL load. Either quant or MySQL replaces the SKU table. Wholesale sales are not read from MySQL.

## Pages

- Home — row counts and which weeks are loaded.
- Data — load tracking, quant, or MySQL.
- Basket SKUs — SKUs for one or more baskets, grouped by SKU, size, brand, name, or basket, with stock and a wholesale count. Filters include SKU, size, brand, name, and a wholesale min and max.
- Wholesale — count wholesale sales by SKU, size, brand, name, or basket, for a sales-order date range.

## Streamlit Community Cloud

This repo is the code only. Community Cloud cannot hold the 2 GB quant file, and it cannot reach a private MySQL host. Keep running the app locally until those sources are replaced by a small extract the cloud app can read.
