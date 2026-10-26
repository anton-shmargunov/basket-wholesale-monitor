"""Shared page controls. Widget values are copied out of Streamlit's widget
state so they survive a switch to another page.
"""

import streamlit as st

from bskuw.dates import DATE_LABEL, PRESETS, preset_range


def restore_widgets(keys):
    """Put saved values back before the widgets are created."""
    for key in keys:
        saved = _saved_name(key)
        if key not in st.session_state and saved in st.session_state:
            st.session_state[key] = st.session_state[saved]


def remember_widgets(keys):
    """Copy current widget values into keys Streamlit will not discard."""
    for key in keys:
        if key in st.session_state:
            st.session_state[_saved_name(key)] = st.session_state[key]


def ensure_choice(key, options, default=None):
    """Keep a select value inside the current options."""
    if not options:
        return
    if key not in st.session_state or st.session_state[key] not in options:
        st.session_state[key] = default if default in options else options[0]


def ensure_subset(key, options):
    """Drop multiselect values that are not in the current options."""
    if key not in st.session_state:
        st.session_state[key] = []
        return
    current = st.session_state[key] or []
    st.session_state[key] = [item for item in current if item in options]


def sale_date_controls(prefix):
    """Incoming-date preset, start, and end. Empty start or end is unlimited."""
    preset_key = prefix + "_preset"
    start_key = prefix + "_start"
    end_key = prefix + "_end"
    hold_key = prefix + "_hold"
    keys = (preset_key, start_key, end_key)
    last_date = _last_quant_date()

    restore_widgets(keys)
    st.session_state[hold_key] = False
    if preset_key not in st.session_state:
        st.session_state[preset_key] = "empty"
    if start_key not in st.session_state:
        st.session_state[start_key] = None
    if end_key not in st.session_state:
        st.session_state[end_key] = None
    if last_date is not None and st.session_state[preset_key] != "empty":
        expected_start, expected_end = preset_range(st.session_state[preset_key], last_date)
        if (
            st.session_state[start_key] != expected_start
            or st.session_state[end_key] != expected_end
        ):
            st.session_state[start_key] = expected_start
            st.session_state[end_key] = expected_end

    def apply_preset():
        st.session_state[hold_key] = True
        start_date, end_date = preset_range(st.session_state[preset_key], last_date)
        st.session_state[start_key] = start_date
        st.session_state[end_key] = end_date

    def dates_edited():
        if st.session_state.get(hold_key):
            return
        st.session_state[preset_key] = "empty"

    if last_date is None:
        st.caption(
            "The quant report has no incoming date to saleable location yet. "
            "Last week, last month, and last year stay empty until that date is known."
        )
    else:
        st.caption(
            "Quant report last incoming date to saleable location: {last_date}. "
            "Last week, last month, and last year end on this date.".format(
                last_date=last_date.isoformat()[:10]
            )
        )

    date_cols = st.columns(3)
    with date_cols[0]:
        st.selectbox(
            DATE_LABEL,
            PRESETS,
            key=preset_key,
            on_change=apply_preset,
            help=(
                "empty clears both dates. Last week is the 7 days ending on the quant report's "
                "last incoming date to saleable location. Last month is the 30 days ending on that date. "
                "Last year is the 365 days ending on that date."
            ),
        )
    with date_cols[1]:
        start = st.date_input(
            "Start",
            key=start_key,
            format="YYYY-MM-DD",
            on_change=dates_edited,
            help="Empty means no lower bound.",
        )
    with date_cols[2]:
        end = st.date_input(
            "End",
            key=end_key,
            format="YYYY-MM-DD",
            on_change=dates_edited,
            help="Empty means no upper bound.",
        )
    remember_widgets(keys)
    return start, end


def _last_quant_date():
    from bskuw import ingest
    from bskuw.queries import quant_report, quant_source_path

    report = quant_report()
    if report["known"]:
        return report["last_sale_date"]
    path = quant_source_path()
    if not path:
        return None
    with st.spinner("Reading the last incoming date to saleable location from the quant report…"):
        try:
            return ingest.capture_quant_last_date(path)
        except Exception as exc:
            st.error(str(exc))
            return None


def _saved_name(key):
    return "_keep_" + key
