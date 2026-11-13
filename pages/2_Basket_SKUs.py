import csv
import io
import numbers

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


def _as_records(edited):
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return [dict(row) for row in edited]


def _is_checked(value):
    try:
        if value != value:
            return False
    except Exception:
        return False
    return bool(value)


def _checked_rows(original, edited):
    """Rows whose Select box is checked, using the original row values."""
    records = _as_records(edited)
    if len(records) != len(original):
        return list(original)
    kept = []
    for source, record in zip(original, records):
        if _is_checked(record.get("Select")):
            kept.append(source)
    return kept


def _stable_value(value):
    """Keep editor data identical across reruns so a click is not dropped."""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return round(float(value), 3)
    return value


def _toggle_header(flags_key, gen_key, all_key, hold_key, count):
    """Header checkbox replaces every row, then the table is shown again."""
    checked = bool(st.session_state.get(all_key))
    st.session_state[flags_key] = [checked] * count
    st.session_state[gen_key] = int(st.session_state.get(gen_key, 0)) + 1
    st.session_state[hold_key] = st.session_state[gen_key]


def _select_editor(rows, key, column_config, header_key):
    """Checkbox as the first column. The header checkbox sets every row."""
    if not rows:
        return []
    all_key = header_key + "_checked"
    gen_key = header_key + "_gen"
    flags_key = header_key + "_flags"
    hold_key = header_key + "_hold"
    seen_key = header_key + "_seen"

    if st.session_state.get(seen_key) != key or len(st.session_state.get(flags_key) or []) != len(rows):
        st.session_state[seen_key] = key
        st.session_state[flags_key] = [True] * len(rows)
        st.session_state[all_key] = True
        st.session_state[gen_key] = int(st.session_state.get(gen_key, 0)) + 1
        st.session_state[hold_key] = st.session_state[gen_key]

    flags = [bool(flag) for flag in st.session_state.get(flags_key)]
    all_on = all(flags)
    if st.session_state.get(all_key) != all_on:
        st.session_state[all_key] = all_on

    with st.container(key=header_key):
        st.checkbox(
            "Select all",
            key=all_key,
            on_change=_toggle_header,
            args=(flags_key, gen_key, all_key, hold_key, len(rows)),
            label_visibility="collapsed",
            help="Check or uncheck every row.",
        )

    flags = [bool(flag) for flag in st.session_state.get(flags_key)]
    table = []
    for row, flag in zip(rows, flags):
        item = {"Select": flag}
        for name, value in row.items():
            item[name] = _stable_value(value)
        table.append(item)
    columns = list(table[0].keys())
    config = {
        "Select": st.column_config.CheckboxColumn(
            "",
            default=True,
            width=64,
            pinned=True,
        )
    }
    config.update(column_config)
    edited = st.data_editor(
        table,
        key="{key}:{gen}".format(key=key, gen=st.session_state.get(gen_key, 0)),
        hide_index=True,
        width="stretch",
        height=420,
        num_rows="fixed",
        disabled=[name for name in columns if name != "Select"],
        column_order=columns,
        column_config=config,
    )
    records = _as_records(edited)
    if len(records) == len(rows):
        new_flags = [_is_checked(record.get("Select")) for record in records]
        gen = int(st.session_state.get(gen_key, 0))
        if new_flags != flags:
            if st.session_state.get(hold_key) == gen:
                # The click that saved these flags was applied again and would clear them.
                st.session_state.pop(hold_key, None)
                st.session_state[gen_key] = gen + 1
            else:
                st.session_state[flags_key] = new_flags
                st.session_state[gen_key] = gen + 1
                st.session_state[hold_key] = gen + 1
            st.rerun()
        else:
            st.session_state.pop(hold_key, None)
    return _checked_rows(rows, edited)


def _editor_key(prefix, identity):
    return "{prefix}-{digest}".format(prefix=prefix, digest=hash(tuple(identity)))


def _sku_pair(row):
    sku = "" if row.get("SKU") is None else str(row.get("SKU")).strip()
    grade = row.get("Grade")
    grade_text = "" if grade is None else str(grade).strip()
    return sku, grade_text


def _saved_flags(header_key, key, count):
    """Flags saved for this table. A new row set starts with every row checked."""
    flags = st.session_state.get(header_key + "_flags")
    if st.session_state.get(header_key + "_seen") != key or len(flags or []) != count:
        return [True] * count
    return [bool(flag) for flag in flags]


def _grouped_editor_key(group_by, rows):
    return _editor_key("basket_grouped", [group_by] + [row.get(group_by) for row in rows])


def _sku_editor_key(rows):
    return _editor_key(
        "basket_skus",
        [(_sku_pair(row)[0], _sku_pair(row)[1], row.get("Basket")) for row in rows],
    )


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _whole_number(value):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return 0
    if value != value:
        return 0
    return int(value)


def _working_rows(grouped_rows, sku_rows, group_by):
    """Filtered rows that the checkboxes still include.

    Checked groups decide which SKUs remain. While every visible SKU row is
    checked, rows past the display limit stay in the totals. Once a SKU row
    is unchecked, only the checked SKU rows are counted.
    """
    group_flags = _saved_flags(
        "bskuw_grouped_header",
        _grouped_editor_key(group_by, grouped_rows),
        len(grouped_rows),
    )
    selected_groups = set(
        row.get(group_by) for row, flag in zip(grouped_rows, group_flags) if flag
    )
    filtered = [row for row in sku_rows if queries.group_value(row, group_by) in selected_groups]
    visible = filtered[:DISPLAY_LIMIT]
    sku_flags = _saved_flags("bskuw_skus_header", _sku_editor_key(visible), len(visible))
    if sku_flags and not all(sku_flags):
        working = [row for row, flag in zip(visible, sku_flags) if flag]
    else:
        working = filtered
    return filtered, working


def _sum_up(rows):
    """Totals for the rows the checkboxes kept. Each saleable tire counts once."""
    skus = set()
    sizes = set()
    brands = set()
    names = set()
    pairs = {}
    unmatched = 0
    for row in rows:
        sku, grade = _sku_pair(row)
        if sku:
            skus.add(sku)
        size = _text(row.get("Size"))
        brand = _text(row.get("Brand"))
        name = _text(row.get("Name"))
        if size:
            sizes.add(size)
        if brand:
            brands.add(brand)
        if name:
            names.add(name)
        if sku and (sku, grade) not in pairs:
            pairs[(sku, grade)] = (
                _whole_number(row.get("Stock on Saleable")),
                _whole_number(row.get("Wholesale")),
            )
        if not size and not brand and not name:
            unmatched += 1
    return {
        "sku_count": len(skus),
        "saleable": sum(item[0] for item in pairs.values()),
        "wholesale": sum(item[1] for item in pairs.values()),
        "size_count": len(sizes),
        "brand_count": len(brands),
        "name_count": len(names),
        "unmatched_rows": unmatched,
    }


def _pairs_from_rows(rows):
    pairs = []
    seen = set()
    for row in rows:
        pair = _sku_pair(row)
        if not pair[0] or pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


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


def _saleable_section(pairs, week, baskets):
    """Quant snapshot for the checked SKUs. Tracking stock is the selected baskets."""
    st.subheader("Saleable stock")
    st.caption(
        "Tires whose Location contains Saleable, for the SKUs checked above. "
        "Each ID is one tire. "
        "Grade A is No Repair and Minor Repair. Grade B is Major Repair and Close to Sidewall. "
        "Stock on Saleable is the quant file on one date. Tracking stock is the weekly average for the selected baskets, and the two can differ."
    )
    if queries.saleable_count() == 0:
        st.caption("Reload the quant report on the Data page. Saleable tires are stored from that file.")
        return
    if not pairs:
        st.caption("Select at least one SKU to see saleable tires.")
        return
    summary = queries.saleable_summary(pairs, week, baskets)
    total = queries.saleable_tire_count(pairs)
    tires = queries.saleable_tires(pairs, limit=DISPLAY_LIMIT)
    if total == 0:
        st.caption("The selected SKUs have no saleable tires in the loaded quant report.")
    elif total > DISPLAY_LIMIT:
        st.caption(
            "Showing the first {limit:,} of {total:,} saleable tires.".format(
                limit=DISPLAY_LIMIT, total=total
            )
        )
    shown_summary = summary[:DISPLAY_LIMIT]
    if len(summary) > DISPLAY_LIMIT:
        st.caption(
            "Showing the first {limit:,} of {total:,} saleable stock rows.".format(
                limit=DISPLAY_LIMIT, total=len(summary)
            )
        )
    st.dataframe(
        shown_summary,
        hide_index=True,
        width="stretch",
        column_config={
            "Stock on Saleable": st.column_config.NumberColumn("Stock on Saleable", format="%d"),
            "Tracking stock": st.column_config.NumberColumn("Tracking stock", format="%.3f"),
        },
    )
    st.dataframe(tires, hide_index=True, width="stretch")
    st.download_button(
        "Download saleable IDs",
        data=_to_csv(tires),
        file_name="saleable-ids.csv",
        mime="text/csv",
        disabled=not tires,
    )


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
st.markdown(
    """
    <style>
    div.st-key-bskuw_grouped_header,
    div.st-key-bskuw_skus_header {
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
        position: relative;
        z-index: 6;
    }
    div.st-key-bskuw_grouped_header [data-testid="stCheckbox"],
    div.st-key-bskuw_skus_header [data-testid="stCheckbox"] {
        position: absolute;
        top: 24px;
        left: 25px;
        width: 28px;
        min-height: 0;
        margin: 0;
        z-index: 6;
    }
    div.st-key-bskuw_grouped_header [data-testid="stCheckbox"] label,
    div.st-key-bskuw_skus_header [data-testid="stCheckbox"] label {
        min-height: 0;
    }
    div.st-key-bskuw_grouped_header [data-testid="stWidgetLabel"],
    div.st-key-bskuw_skus_header [data-testid="stWidgetLabel"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Basket SKUs")
st.caption(
    "SKUs in the selected baskets for one week. "
    "Tracking Stock is the tracking basket average for that week. "
    "Stock on Saleable counts tires whose quant location contains Saleable. "
    "Wholesale is how many times that SKU was sold as wholesale in the incoming-date range. "
    "Grade A and grade B are separate rows. "
    "Tracking Stock follows the tracking grade. "
    "Stock on Saleable and wholesale follow that grade's Majority, including a grade that has no stock row. "
    "Wholesale min and max keep rows whose own count is inside the range. "
    "A SKU in two selected baskets shows the same saleable count and the same wholesale count on both rows of that grade. "
    "The Grouped and SKU tables start with every row checked. "
    "Uncheck a group to drop its SKUs from the SKU table and the totals. "
    "Uncheck a SKU row to drop that SKU and grade from the totals and from saleable stock."
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
            "Tracking Stock of a grade comes from the tracking file. "
            "Stock on Saleable and wholesale of a grade come from Majority on each tire, even when that grade has no stock."
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
        "Not in Basket lists SKUs with a wholesale sale that are not in this week's tracking report. Those SKUs have no Tracking Stock."
    )
elif include_outside:
    st.caption(
        "Total includes wholesale sales of SKUs that are not in this week's tracking report. Those SKUs have no Tracking Stock."
    )

grouped_rows = queries.basket_grouped(
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
)
sku_rows = queries.basket_rows(
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
    start=start,
    end=end,
    wholesale_min=wholesale_min,
    wholesale_max=wholesale_max,
    include_outside=include_outside,
    outside_only=outside_only,
    grade=grade,
    treads=chosen_treads,
)
filtered_rows, working_rows = _working_rows(grouped_rows, sku_rows, group_by)
summary = _sum_up(working_rows)
sku_col, stock_col, wholesale_col = st.columns(3)
sku_col.metric("SKUs", "{:,}".format(summary["sku_count"]))
stock_col.metric("Stock on Saleable", "{:,}".format(summary["saleable"]))
wholesale_col.metric("Wholesale", "{:,}".format(summary["wholesale"]))
size_col, brand_col, name_col = st.columns(3)
size_col.metric("Sizes", "{:,}".format(summary["size_count"]))
brand_col.metric("Brands", "{:,}".format(summary["brand_count"]))
name_col.metric("Names", "{:,}".format(summary["name_count"]))
st.caption(
    "Totals follow the checked rows. "
    "Uncheck a group to drop its SKUs. "
    "While every SKU row stays checked, totals include filtered rows past the display limit. "
    "Uncheck a SKU row and the totals use only the checked SKU rows. "
    "Stock on Saleable counts each saleable tire once."
)

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
    st.caption("Wholesale and Stock on Saleable count each tire once. These SKUs are not in this week's tracking report and have no Tracking Stock.")
elif group_by == "Basket":
    st.caption(
        "Tracking Stock is summed inside each basket. "
        "Stock on Saleable and a wholesale sale are counted in every selected basket that contains that SKU and grade."
        + (
            " (no basket) holds sales whose SKU is not in this week's tracking report."
            if include_outside
            else ""
        )
    )
else:
    st.caption(
        "Tracking Stock is summed across the selected baskets. Stock on Saleable and wholesale count each tire once."
        + (
            " Sales of SKUs that are not in this week's tracking report are included."
            if include_outside
            else ""
        )
    )
number_columns = {
    "Tracking Stock": st.column_config.NumberColumn("Tracking Stock", format="%.3f"),
    "Stock on Saleable": st.column_config.NumberColumn("Stock on Saleable", format="%d"),
    "Wholesale": st.column_config.NumberColumn("Wholesale", format="%d"),
}
st.caption(
    "Every group starts checked. The checkbox in the Select header checks or unchecks every group. "
    "Uncheck one row to leave its SKUs out of the tables and totals below."
)
kept_groups = _select_editor(
    grouped_rows,
    _grouped_editor_key(group_by, grouped_rows),
    number_columns,
    "bskuw_grouped_header",
)
selected_groups = set(row.get(group_by) for row in kept_groups)
filtered_rows = [row for row in sku_rows if queries.group_value(row, group_by) in selected_groups]

st.subheader("SKUs")
visible = filtered_rows[:DISPLAY_LIMIT]
if len(filtered_rows) > DISPLAY_LIMIT:
    st.caption(
        "Showing the first {limit:,} of {total:,} rows. Saleable stock follows the checked rows in this table.".format(
            limit=DISPLAY_LIMIT, total=len(filtered_rows)
        )
    )
st.caption(
    "Every SKU row starts checked. The checkbox in the Select header checks or unchecks every row. "
    "Stock on Saleable is the saleable tires of that SKU and grade. "
    "Uncheck one row to leave that SKU and grade out of the totals and out of saleable stock."
)
kept_visible = _select_editor(
    visible,
    _sku_editor_key(visible),
    number_columns,
    "bskuw_skus_header",
)
saleable_pairs = _pairs_from_rows(kept_visible)
st.download_button(
    "Download CSV",
    data=_to_csv(filtered_rows),
    file_name="basket-skus-{week}.csv".format(week=week),
    mime="text/csv",
    disabled=not filtered_rows,
)

_saleable_section(
    saleable_pairs,
    week,
    None if outside_only else query_baskets,
)
