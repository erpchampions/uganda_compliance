"""Date helpers for EFRIS payloads (no frappe import, so they are unit-testable)."""
import datetime


def efris_date_str(value):
    """Return a date/datetime/str as the 'YYYY-MM-DD' string EFRIS expects.

    Documents hand over `posting_date` as a datetime.date; json.dumps cannot
    serialise that and the whole request fails before encryption. The Purchase
    Receipt path already stringifies the date - this does the same, uniformly.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)[:10]
