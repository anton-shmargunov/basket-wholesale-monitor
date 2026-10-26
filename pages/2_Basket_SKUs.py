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
    "basket_tread",
    "basket_size",
    "basket_section",
    "basket_aspect",
    "basket_rim",
    "basket_brand",
    "basket_name",
    "basket_grade",
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
    "Wholesale is how many times that SKU was sold as wholesale in the incoming-date range. "
    "Grade A and grade B are separate rows. "
    "Stock is the tracking grade. "
    "Wholesale is that grade's Majority, including a grade that has no stock row. "
    "Wholesale min and max keep rows whose own count is inside the range. "
    "A SKU in two selected baskets shows the same wholesale count on both rows of that grade."
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
ensure_choice("basket_group", queries.WHOLESALE_GROUPS, default="Size")
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
tread_values = queries.list_treads()
ensure_subset("basket_tread", tread_values)

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
        sku = st.text_input("SKU", key="basket_sku", help="Exact SKU. Empty means any SKU.")
        chosen_treads = st.multiselect(
            "Tread",
            tread_values,
            placeholder="All",
            key="basket_tread",
            help="Empty means any tread. Values come from the Tread column in the quant report.",
        )
    st.session_state["_basket_baskets_prev"] = list(chosen_baskets or [])
    with filter_cols[1]:
        chosen_product_bs = st.multiselect(
            "Product BS",
            product_bs_values,
            placeholder="All",
            key="basket_product_bs",
        )
        brand = st.text_input("Brand", key="basket_brand", help="Exact brand. Empty means any brand.")
        name = st.text_input("Name contains", key="basket_name")
        ensure_choice("basket_grade", queries.GRADE_OPTIONS, default="")
        grade = st.selectbox(
            "Grade",
            queries.GRADE_OPTIONS,
            key="basket_grade",
            format_func=lambda value: value if value else " ",
            help=queries.GRADE_HELP,
        )
    with st.container(border=True):
        st.caption("Size")
        size_cols = st.columns(4)
        with size_cols[0]:
            size = st.text_input("Size", key="basket_size", help="Exact size. Empty means any size.")
        with size_cols[1]:
            section = st.text_input("Section", key="basket_section", help="Exact section. Empty means any section.")
        with size_cols[2]:
            aspect = st.text_input("Aspect", key="basket_aspect", help="Exact aspect. Empty means any aspect.")
        with size_cols[3]:
            rim = st.text_input("Rim", key="basket_rim", help="Exact rim. Empty means any rim.")
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
if grade in ("A", "B"):
    loaded_grade = queries.grade_data_loaded()
    if not loaded_grade["tracking"] or not loaded_grade["wholesale"]:
        st.info(
            "Reload the tracking report and the quant report on the Data page. "
            "Stock of a grade comes from the tracking file. "
            "Wholesale of a grade comes from Majority on each tire, even when that grade has no stock."
        )

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
    section,
    aspect,
    rim,
    brand,
    name,
    start,
    end,
    wholesale_min,
    wholesale_max,
    include_outside,
    outside_only,
    grade,
    treads=chosen_treads,
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
if outside_only and group_by == "Basket":
    st.caption("These SKUs are not in this week's tracking report, so they sit in (no basket).")
elif outside_only:
    st.caption("Wholesale counts each tire once. These SKUs are not in this week's tracking report and have no stock.")
elif group_by == "Basket":
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
        section,
        aspect,
        rim,
        brand,
        name,
        group_by,
        start,
        end,
        wholesale_min,
        wholesale_max,
        include_outside,
        outside_only,
        grade,
        treads=chosen_treads,
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
    section,
    aspect,
    rim,
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
    grade=grade,
    treads=chosen_treads,
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
        grade=grade,
        treads=chosen_treads,
    )
)
st.download_button(
    "Download CSV",
    data=_to_csv(full_rows),
    file_name="basket-skus-{week}.csv".format(week=week),
    mime="text/csv",
    disabled=not full_rows,
)
