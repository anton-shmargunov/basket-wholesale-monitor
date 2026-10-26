from pathlib import Path

import streamlit as st

from bskuw import ingest
from bskuw.db import export_snapshot, get_connection, replace_database
from bskuw.paths import DB_PATH, DEFAULT_QUANT, DEFAULT_TRACKING, UPLOAD_DIR
from bskuw.settings import SecretsError, mysql_settings_or_none
from bskuw.ui import remember_widgets, restore_widgets


def _default_text(path):
    return str(path) if path.is_file() else ""


def _uploaded_path(uploaded):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / uploaded.name
    destination.write_bytes(uploaded.getbuffer())
    return destination


get_connection()
restore_widgets(("data_tracking_path", "data_quant_path"))
if "data_tracking_path" not in st.session_state:
    st.session_state["data_tracking_path"] = _default_text(DEFAULT_TRACKING)
if "data_quant_path" not in st.session_state:
    st.session_state["data_quant_path"] = _default_text(DEFAULT_QUANT)

st.title("Data")
st.caption(
    "The working database is {path}. It stays outside this project folder, so Google Drive does not lock it. "
    "Download it to keep another copy. Upload that file to use it again, including after the online app restarts.".format(
        path=DB_PATH
    )
)

st.subheader("Database file")
if st.button("Prepare a copy"):
    with st.spinner("Writing a copy of the database…"):
        snapshot = export_snapshot()
    st.session_state["db_export_path"] = str(snapshot)
export_path = st.session_state.get("db_export_path")
export_file = Path(export_path) if export_path else None
if export_file is not None and export_file.is_file():
    st.download_button(
        "Download database",
        data=export_file.read_bytes(),
        file_name="bskuw.duckdb",
        mime="application/octet-stream",
    )
database_upload = st.file_uploader("Upload a saved database", type=["duckdb"])
if st.button("Use this database", disabled=database_upload is None):
    try:
        with st.spinner("Opening the uploaded database…"):
            replace_database(database_upload.getvalue())
        st.session_state.pop("db_export_path", None)
        st.success("This database is now the one the app reads.")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

st.subheader("Tracking basket report")
st.caption(
    "xlsx or csv, about 5 MB. A new file replaces the weeks it contains. An upload is used instead of the path. "
    "Grade is kept when the file has that column. One SKU can be grade A and grade B."
)
tracking_upload = st.file_uploader("Upload a tracking export", type=["xlsx", "csv"])
tracking_path = st.text_input("Or tracking file path", key="data_tracking_path")
if st.button("Load tracking", type="primary"):
    try:
        source = _uploaded_path(tracking_upload) if tracking_upload is not None else tracking_path
        with st.spinner("Reading the tracking export…"):
            result = ingest.load_tracking(source)
        st.success(
            "Loaded {rows:,} SKU rows for {weeks} ({baskets} baskets).".format(
                rows=result["rows"],
                weeks=", ".join(result["weeks"]),
                baskets=result["baskets"],
            )
        )
    except Exception as exc:
        st.error(str(exc))

st.subheader("Quant report")
st.caption(
    "CSV, about 2 GB. Paste a path. The uploader is not used because the file is larger than Streamlit's upload limit. "
    "This replaces the SKU attribute table and the wholesale sales. "
    "A wholesale sale is a tire at {location}. "
    "Each SKU keeps Tread. Each sale keeps its Majority, which is how Grade A and Grade B split wholesale.".format(
        location=ingest.WHOLESALE_LOCATION
    )
)
quant_path = st.text_input("Quant CSV path", key="data_quant_path")
remember_widgets(("data_tracking_path", "data_quant_path"))
if st.button("Load quant"):
    try:
        with st.spinner("Reading the quant report…"):
            result = ingest.load_quant(quant_path)
        last_date = result["last_sale_date"]
        last_text = last_date.isoformat()[:10] if last_date is not None else "none"
        st.success(
            "Loaded {rows:,} SKUs and {wholesale:,} wholesale sales. Last incoming date to saleable location: {last}.".format(
                rows=result["rows"],
                wholesale=result["wholesale_rows"],
                last=last_text,
            )
        )
        if result["unparsed_dates"]:
            st.warning(
                "{count:,} wholesale sales have a date that could not be read. They stay in the total, and drop out when a start or end date is set.".format(
                    count=result["unparsed_dates"]
                )
            )
    except Exception as exc:
        st.error(str(exc))

st.subheader("MySQL — clear_data.clear_sku")
st.caption(
    "Reads sku, name, brand, model, size, tread, and condition. Internal category and majority stay empty. "
    "Wholesale sales are not read from MySQL."
)
mysql = mysql_settings_or_none()
if mysql is None:
    st.info(
        "MySQL is not configured. Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml "
        "and set host, port, user, password, and database."
    )
else:
    st.caption(
        "Connecting as {user}@{host}:{port}, database {database}.".format(
            user=mysql["user"],
            host=mysql["host"],
            port=mysql["port"],
            database=mysql["database"],
        )
    )
if st.button("Load from MySQL"):
    try:
        with st.spinner("Reading clear_data.clear_sku…"):
            result = ingest.load_mysql()
        st.success("Loaded {rows:,} SKUs from MySQL.".format(rows=result["rows"]))
    except SecretsError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(str(exc))
