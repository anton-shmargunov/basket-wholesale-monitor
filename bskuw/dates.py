"""Incoming-date presets for Basket SKUs and Wholesale."""

from datetime import date, datetime, timedelta

PRESETS = ("empty", "last week", "last month", "last year")
DATE_LABEL = "Incoming date to saleable location"

# Inclusive lengths. The end date is the latest incoming date in the quant report,
# so the start is 6, 29, or 364 days earlier.
_PRESET_DAYS_BEFORE = {
    "last week": 6,
    "last month": 29,
    "last year": 364,
}


def preset_range(name, last_date):
    """Return an inclusive start and end for a preset.

    empty clears both bounds. last week, last month, and last year end on
    last_date and cover 7, 30, and 365 days. None means that side is unlimited.
    """
    days_before = _PRESET_DAYS_BEFORE.get(name)
    last_date = _as_date(last_date)
    if days_before is None or last_date is None:
        return None, None
    return last_date - timedelta(days=days_before), last_date


def describe_range(start, end):
    """Describe the inclusive filter. None on either side means unlimited."""
    start = _as_date(start)
    end = _as_date(end)
    if start is not None and end is not None and start > end:
        return "Start is after end."
    if start is None and end is None:
        return "{label}: any date.".format(label=DATE_LABEL)
    if start is None:
        return "{label}: through {end}.".format(label=DATE_LABEL, end=end.isoformat())
    if end is None:
        return "{label}: from {start}.".format(label=DATE_LABEL, start=start.isoformat())
    return "{label}: {start} to {end}.".format(label=DATE_LABEL, start=start.isoformat(), end=end.isoformat())


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
