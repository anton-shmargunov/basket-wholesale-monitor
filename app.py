import streamlit as st

from bskuw import queries
from bskuw.db import get_connection


def home():
    get_connection()
    st.title("Basket-Wholesale Monitor (BWM)")
    st.caption("v.1.0.1")
    st.caption("Tracking baskets, SKU attributes, and wholesale sales on this machine.")
    st.caption("On Data, download the database to keep a copy on your computer. Upload that file to open it again.")

    info = queries.status()
    tracking_col, sku_col, wholesale_col = st.columns(3)
    tracking_col.metric("Tracking rows", "{:,}".format(info["tracking_rows"]))
    sku_col.metric("SKU attributes", "{:,}".format(info["sku_rows"]))
    wholesale_col.metric("Wholesale sales", "{:,}".format(info["wholesale_rows"]))

    if info["sku_source"]:
        st.caption("SKU attributes loaded from {}.".format(info["sku_source"]))
    elif info["tracking_rows"]:
        st.caption("Sizes, brands, and names stay blank until a quant file or MySQL is loaded on Data.")

    if info["weeks"]:
        st.subheader("Weeks in the tracking table")
        st.dataframe(info["weeks"], hide_index=True, width="stretch")
    else:
        st.info("No tracking data yet. Open Data and load a tracking basket report.")


st.set_page_config(page_title="Basket-Wholesale Monitor (BWM)", layout="wide")
st.navigation(
    [
        st.Page(home, title="Home", default=True),
        st.Page("pages/1_Data.py", title="Data"),
        st.Page("pages/2_Basket_SKUs.py", title="Basket SKUs"),
        st.Page("pages/3_Wholesale.py", title="Wholesale"),
    ]
).run()
