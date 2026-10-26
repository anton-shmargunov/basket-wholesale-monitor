import streamlit as st

from bskuw import queries
from bskuw.dates import describe_range
from bskuw.db import get_connection
from bskuw.ingest import WHOLESALE_LOCATION
from bskuw.ui import ensure_choice, ensure_subset, remember_widgets, restore_widgets, sale_date_controls

FILTER_KEYS = (
    "wholesale_week",
    "wholesale_baskets",
    "wholesale_sku",
    "wholesale_tread",
    "wholesale_size",
    "wholesale_section",
    "wholesale_aspect",
    "wholesale_rim",
    "wholesale_brand",
    "wholesale_name",
    "wholesale_grade",
    "wholesale_group",
)


get_connection()
restore_widgets(FILTER_KEYS)

st.title("Wholesale")
st.caption(
    "A wholesale sale is one tire at {location}. "
    "The count comes from the quant report. MySQL is not used for this.".format(location=WHOLESALE_LOCATION)
)

loaded = queries.status()
if loaded["wholesale_rows"] == 0:
    st.warning("No wholesale sales are loaded. Load a quant report on the Data page.")

start, end = sale_date_controls("wholesale")
st.caption(describe_range(start, end) + " Both bounds are inclusive.")

weeks = queries.list_weeks()
week = None
baskets = []
shown = []
if weeks:
    ensure_choice("wholesale_week", weeks)
    week = st.selectbox("Basket week", weeks, key="wholesale_week")
    baskets = queries.list_baskets(week)
    shown.append("wholesale_week")
else:
    st.info("Load a tracking basket report to limit the count to baskets.")

filter_cols = st.columns(2)
with filter_cols[0]:
    if baskets:
        ensure_subset("wholesale_baskets", baskets)
        chosen_baskets = st.multiselect("Baskets", baskets, key="wholesale_baskets")
        shown.append("wholesale_baskets")
    else:
        chosen_baskets = []
    sku = st.text_input("SKU", key="wholesale_sku", help="Exact SKU. Empty means any SKU.")
    tread_values = queries.list_treads()
    ensure_subset("wholesale_tread", tread_values)
    chosen_treads = st.multiselect(
        "Tread",
        tread_values,
        placeholder="All",
        key="wholesale_tread",
        help="Empty means any tread. Values come from the Tread column in the quant report.",
    )
with filter_cols[1]:
    ensure_choice("wholesale_group", queries.WHOLESALE_GROUPS)
    group_by = st.selectbox("Group by", queries.WHOLESALE_GROUPS, key="wholesale_group")
    brand = st.text_input("Brand", key="wholesale_brand", help="Exact brand. Empty means any brand.")
    name = st.text_input("Name contains", key="wholesale_name")
    ensure_choice("wholesale_grade", queries.GRADE_OPTIONS, default="")
    grade = st.selectbox(
        "Grade",
        queries.GRADE_OPTIONS,
        key="wholesale_grade",
        format_func=lambda value: value if value else " ",
        help=queries.GRADE_HELP,
    )
with st.container(border=True):
    st.caption("Size")
    size_cols = st.columns(4)
    with size_cols[0]:
        size = st.text_input("Size", key="wholesale_size", help="Exact size. Empty means any size.")
    with size_cols[1]:
        section = st.text_input("Section", key="wholesale_section", help="Exact section. Empty means any section.")
    with size_cols[2]:
        aspect = st.text_input("Aspect", key="wholesale_aspect", help="Exact aspect. Empty means any aspect.")
    with size_cols[3]:
        rim = st.text_input("Rim", key="wholesale_rim", help="Exact rim. Empty means any rim.")
shown.extend(
    [
        "wholesale_sku",
        "wholesale_tread",
        "wholesale_size",
        "wholesale_section",
        "wholesale_aspect",
        "wholesale_rim",
        "wholesale_group",
        "wholesale_brand",
        "wholesale_name",
        "wholesale_grade",
    ]
)
remember_widgets(shown)

if start is not None and end is not None and start > end:
    st.error("Start is after end.")
    st.stop()

unparsed = queries.wholesale_unparsed_dates()
if unparsed and (start is not None or end is not None):
    st.caption(
        "{count:,} sales have a date that could not be read, so they are left out of this range.".format(
            count=unparsed
        )
    )

if grade in ("A", "B"):
    loaded_grade = queries.grade_data_loaded()
    if not loaded_grade["tracking"] or not loaded_grade["wholesale"]:
        st.info(
            "Reload the tracking report and the quant report on the Data page. "
            "Stock of a grade comes from the tracking file. "
            "Wholesale of a grade comes from Majority on each tire, even when that grade has no stock."
        )

if group_by == "Basket" and not weeks:
    st.info("Grouping by basket needs a tracking report.")
    st.stop()

if not chosen_baskets and group_by != "Basket":
    st.caption("No baskets selected, so this is every wholesale sale in the date range.")
if group_by == "Basket":
    st.caption(
        "Grouped by basket, a sale is counted in every matching basket that contains its SKU. "
        "Adding those basket totals together counts that sale more than once. The Sold total counts each sale once."
    )

sold = queries.wholesale_count(
    week, chosen_baskets, sku, size, section, aspect, rim, brand, name, start, end, grade, chosen_treads
)
st.metric("Sold", "{:,}".format(sold))

rows = queries.wholesale_summary(
    week, chosen_baskets, sku, size, section, aspect, rim, brand, name, group_by, start, end, grade, chosen_treads
)
if not rows:
    st.info("No wholesale sales match these filters.")
else:
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={"Sold": st.column_config.NumberColumn("Sold", format="%d")},
    )
