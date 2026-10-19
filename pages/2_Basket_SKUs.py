import csv
import io

import streamlit as st

from bskuw import queries
from bskuw.dates import describe_range
from bskuw.db import get_connection
from bskuw.ui import ensure_choice, ensure_subset, remember_widgets, restore_widgets, sale_date_controls

DISPLAY_LIMIT = 5000
TOTAL = "Total"
TOTAL_BASKETS = "Total baskets"
NOT_IN_BASKET = "Not in Basket"
_BASKET_TOTALS = (TOTAL, TOTAL_BASKETS, NOT_IN_BASKET)
FILTER_KEYS = (
    "basket_week",
    "basket_baskets",
    "basket_product_bs",
    "basket_sku",
    "basket_size",
    "basket_brand",
    "basket_name",
    "basket_group",
    "basket_wholesale_min",
    "basket_wholesale_max",
)


def _to_csv(rows):
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _baskets_changed():
    """Total, Total baskets, and Not in Basket stand alone."""
    chosen = list(st.session_state.get("basket_baskets") or [])
    previous = list(st.session_state.get("_basket_baskets_prev") or [])
    specials = [item for item in chosen if item in _BASKET_TOTALS]
    if specials and len(chosen) > 1:
        added = [item for item in chosen if item not in previous]
        added_specials = [item for item in added if item in _BASKET_TOTALS]
        if added_specials:
            chosen = [added_specials[-1]]
        else:
            chosen = [item for item in chosen if item not in _BASKET_TOTALS]
        st.session_state["basket_baskets"] = chosen


def _optional_number(key):
    if key not in st.session_state:
        st.session_state[key] = None
    return st.number_input(
        "Wholesale min" if key.endswith("_min") else "Wholesale max",
        min_value=0,
        step=1,
        format="%d",
        key=key,
        help="Empty means this side is unlimited. The range is inclusive.",
    )


get_connection()
st.title("Basket SKUs")
st.caption(
    "SKUs in the selected baskets for one week. "
    "Stock is that week's snapshot. "
    "Wholesale is how many times that SKU was sold as wholesale in the sales-order date range. "
    "Wholesale min and max keep SKUs whose own count is inside the range. "
    "A SKU in two selected baskets shows the same wholesale count on both rows of the SKU table."
)

restore_widgets(FILTER_KEYS)
start, end = sale_date_controls("basket_sale")
st.caption(describe_range(start, end) + " Both bounds are inclusive.")

if queries.status()["tracking_rows"] == 0:
    st.info("Load a tracking basket report on the Data page.")
    remember_widgets(FILTER_KEYS)
    st.stop()

weeks = queries.list_weeks()
ensure_choice("basket_week", weeks)
ensure_choice("basket_group", queries.WHOLESALE_GROUPS, default="size")
scope_cols = st.columns(2)
with scope_cols[0]:
    week = st.selectbox("Week", weeks, key="basket_week")
with scope_cols[1]:
    group_by = st.selectbox("Group by", queries.WHOLESALE_GROUPS, key="basket_group")

baskets = queries.list_baskets(week)
basket_options = [TOTAL, TOTAL_BASKETS, NOT_IN_BASKET] + list(baskets)
product_bs_values = queries.list_product_bs(week)
ensure_subset("basket_baskets", basket_options)
ensure_subset("basket_product_bs", product_bs_values)

with st.container(border=True):
    st.markdown("**Filters**")
    filter_cols = st.columns(2)
    with filter_cols[0]:
        chosen_baskets = st.multiselect(
            "Baskets",
            basket_options,
            key="basket_baskets",
            on_change=_baskets_changed,
            help=(
                "Total includes every SKU in this week's tracking baskets, and every SKU with a "
                "wholesale sale that is not in that report. Total baskets includes only the tracking SKUs. "
                "Not in Basket includes only those wholesale SKUs."
            ),
        )
        sku = st.text_input("SKU contains", key="basket_sku")
        size = st.text_input("Size contains", key="basket_size")
    st.session_state["_basket_baskets_prev"] = list(chosen_baskets or [])
    with filter_cols[1]:
        chosen_product_bs = st.multiselect(
            "Product BS",
            product_bs_values,
            placeholder="All",
            key="basket_product_bs",
        )
        brand = st.text_input("Brand contains", key="basket_brand")
        name = st.text_input("Name contains", key="basket_name")
    with st.container(border=True):
        st.caption("Wholesale")
        wholesale_cols = st.columns(2)
        with wholesale_cols[0]:
            wholesale_min = _optional_number("basket_wholesale_min")
        with wholesale_cols[1]:
            wholesale_max = _optional_number("basket_wholesale_max")
remember_widgets(FILTER_KEYS)

if start is not None and end is not None and start > end:
    st.error("Start is after end.")
    st.stop()
if wholesale_min is not None and wholesale_max is not None and wholesale_min > wholesale_max:
    st.error("Wholesale min is above max.")
    st.stop()

unparsed = queries.wholesale_unparsed_dates()
if unparsed and (start is not None or end is not None):
    st.caption(
        "{count:,} sales have a date that could not be read, so they are left out of this range.".format(
            count=unparsed
        )
    )

outside_only = NOT_IN_BASKET in chosen_baskets
include_outside = TOTAL in chosen_baskets
if include_outside or TOTAL_BASKETS in chosen_baskets:
    query_baskets = list(baskets)
else:
    query_baskets = [item for item in chosen_baskets if item not in _BASKET_TOTALS]
if not query_baskets and not outside_only:
    st.info("Select one or more baskets.")
    st.stop()
if (include_outside or outside_only) and chosen_product_bs:
    st.caption("Product BS is set, so SKUs that are not in the tracking report are left out.")
elif outside_only:
    st.caption(
        "Not in Basket lists SKUs with a wholesale sale that are not in this week's tracking report. Those SKUs have no stock."
    )
elif include_outside:
    st.caption(
        "Total includes wholesale sales of SKUs that are not in this week's tracking report. Those SKUs have no stock."
    )

summary = queries.basket_summary(
    week,
    query_baskets,
    chosen_product_bs,
    sku,
    size,
    brand,
    name,
    start,
    end,
    wholesale_min,
    wholesale_max,
    include_outside,
    outside_only,
)
sku_col, stock_col, wholesale_col = st.columns(3)
sku_col.metric("SKUs", "{:,}".format(summary["sku_count"]))
stock_col.metric("Stock", "{:,.3f}".format(summary["stock_qty_w"]))
wholesale_col.metric("Wholesale", "{:,}".format(summary["wholesale"]))
size_col, brand_col, name_col = st.columns(3)
size_col.metric("Sizes", "{:,}".format(summary["size_count"]))
brand_col.metric("Brands", "{:,}".format(summary["brand_count"]))
name_col.metric("Names", "{:,}".format(summary["name_count"]))

if summary["unmatched_rows"]:
    unmatched = summary["unmatched_rows"]
    st.caption(
        "{unmatched:,} {noun} {verb} no SKU attributes. Load the quant report or MySQL on the Data page to fill size, brand, and name.".format(
            unmatched=unmatched,
            noun="row" if unmatched == 1 else "rows",
            verb="has" if unmatched == 1 else "have",
        )
    )

st.subheader("Grouped")
if outside_only and group_by == "basket":
    st.caption("These SKUs are not in this week's tracking report, so they sit in (no basket).")
elif outside_only:
    st.caption("Wholesale counts each tire once. These SKUs are not in this week's tracking report and have no stock.")
elif group_by == "basket":
    st.caption(
        "Stock is summed inside each basket. "
        "A wholesale sale is counted in every selected basket that contains its SKU."
        + (
            " (no basket) holds sales whose SKU is not in this week's tracking report."
            if include_outside
            else ""
        )
    )
else:
    st.caption(
        "Stock is summed across the selected baskets. Wholesale counts each tire once."
        + (
            " Sales of SKUs that are not in this week's tracking report are included."
            if include_outside
            else ""
        )
    )
st.dataframe(
    queries.basket_grouped(
        week,
        query_baskets,
        chosen_product_bs,
        sku,
        size,
        brand,
        name,
        group_by,
        start,
        end,
        wholesale_min,
        wholesale_max,
        include_outside,
        outside_only,
    ),
    hide_index=True,
    width="stretch",
    column_config={
        "Stock": st.column_config.NumberColumn("Stock", format="%.3f"),
        "Wholesale": st.column_config.NumberColumn("Wholesale", format="%d"),
    },
)

st.subheader("SKUs")
total_rows = summary["rows"]
row_args = (
    week,
    query_baskets,
    chosen_product_bs,
    sku,
    size,
    brand,
    name,
)
visible = queries.basket_rows(
    *row_args,
    limit=DISPLAY_LIMIT,
    start=start,
    end=end,
    wholesale_min=wholesale_min,
    wholesale_max=wholesale_max,
    include_outside=include_outside,
    outside_only=outside_only,
)
if total_rows > DISPLAY_LIMIT:
    st.caption("Showing the first {limit:,} of {total:,} rows.".format(limit=DISPLAY_LIMIT, total=total_rows))
st.dataframe(
    visible,
    hide_index=True,
    width="stretch",
    column_config={
        "Stock": st.column_config.NumberColumn("Stock", format="%.3f"),
        "Wholesale": st.column_config.NumberColumn("Wholesale", format="%d"),
    },
)

full_rows = (
    visible
    if total_rows <= DISPLAY_LIMIT
    else queries.basket_rows(
        *row_args,
        start=start,
        end=end,
        wholesale_min=wholesale_min,
        wholesale_max=wholesale_max,
        include_outside=include_outside,
        outside_only=outside_only,
    )
)
st.download_button(
    "Download CSV",
    data=_to_csv(full_rows),
    file_name="basket-skus-{week}.csv".format(week=week),
    mime="text/csv",
    disabled=not full_rows,
)
