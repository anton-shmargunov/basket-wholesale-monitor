from pathlib import Path

import streamlit as st

from bskuw import queries
from bskuw.db import get_connection

LOGO = Path(__file__).resolve().parent / "assets" / "sidebar_transparent.png"


def home():
    get_connection()
    st.title("Basket-Wholesale Monitor (BWM)")
    st.caption("v.1.0.2")
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


st.set_page_config(
    page_title="Basket-Wholesale Monitor (BWM)",
    page_icon=str(LOGO),
    layout="wide",
)
with st.sidebar:
    st.image(str(LOGO), width="stretch")
st.markdown(
    """
    <style>
    [data-testid="stSidebarContent"] {
        display: flex;
        flex-direction: column;
    }
    [data-testid="stSidebarHeader"] { order: 0; }
    [data-testid="stSidebarUserContent"] { order: 1; }
    [data-testid="stSidebarNav"] { order: 2; }
    [data-testid="stSidebarUserContent"] [data-testid="stImage"] {
        width: 60%;
        margin-left: auto;
        margin-right: auto;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.navigation(
    [
        st.Page(home, title="Home", default=True),
        st.Page("pages/1_Data.py", title="Data"),
        st.Page("pages/2_Basket_SKUs.py", title="Basket SKUs"),
        st.Page("pages/3_Wholesale.py", title="Wholesale"),
    ]
).run()
