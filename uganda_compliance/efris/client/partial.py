"""Partial-failure extraction.

URA's batch endpoints (T130 goods upload, T109 invoice upload, T131 stock-in,
etc.) return `returnMessage="Partial failure!"` at the envelope level when at
least one row fails. The actionable per-row reasons live inside the encrypted
`data.content`, keyed by interface (e.g. `goodsUploadingList`).

The legacy transport never decrypted on a non-SUCCESS envelope, so callers
saw only the literal string "Partial failure!" with no field-level reason.
This module pulls those reasons out so `EfrisError.partial_failures` carries
useful diagnostics (commodityCategoryId, measureUnit, currency, goodsCode...).
"""

# Per-interface mapping: where to find the per-row results array, and which
# field flags a row as failed.
_PARTIAL_LAYOUTS: dict[str, tuple[str, str, str]] = {
    # interfaceCode: (results_key, identifier_field, failure_message_field)
    "T130": ("goodsUploadingList", "goodsCode", "remarks"),
    "T131": ("stockInOutList", "goodsCode", "remarks"),
    "T109": ("einvoiceUploadingList", "invoiceNo", "remarks"),
    "T131A": ("stockInOutList", "goodsCode", "remarks"),
}


def is_partial(return_message: str | None) -> bool:
    if not return_message:
        return False
    msg = return_message.lower()
    return "partial" in msg


def extract(interface_code: str, decoded_content: dict | list | None) -> list[dict]:
    """Pull per-row failures out of a decoded EFRIS response."""
    if not decoded_content:
        return []

    layout = _PARTIAL_LAYOUTS.get(interface_code)
    if not layout:
        return _generic_extract(decoded_content)

    results_key, id_field, msg_field = layout
    rows = _find_rows(decoded_content, results_key)
    failures = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if _row_failed(row):
            failures.append(
                {
                    "id": row.get(id_field) or row.get("goodsName") or row.get("invoiceNo"),
                    "message": row.get("returnMessage") or row.get(msg_field),
                    "row": row,
                }
            )
    return failures


def _find_rows(content, key):
    if isinstance(content, list):
        if content and isinstance(content[0], dict) and any(
            k in content[0] for k in ("returnCode", "returnMessage", "remarks", "errorMsg")
        ):
            return content
        for item in content:
            found = _find_rows(item, key)
            if found:
                return found
        return None
    if isinstance(content, dict):
        if key in content:
            return content[key]
        for v in content.values():
            found = _find_rows(v, key)
            if found:
                return found
    return None


def _row_failed(row: dict) -> bool:
    """A row is a failure if it carries an error field or a non-success code."""
    if row.get("returnCode") and str(row.get("returnCode")) not in ("00", "0", ""):
        return True
    if row.get("status") and str(row.get("status")).lower() in ("fail", "failed", "error"):
        return True
    if row.get("remarks"):
        return True
    return False


def _generic_extract(content):
    """Fallback for interfaces we haven't mapped — surface anything that looks
    like a row-level failure so operators have something to act on."""
    if isinstance(content, dict):
        # Look for any list value whose entries have a `remarks` or `returnCode`.
        for v in content.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if any(k in v[0] for k in ("remarks", "returnCode", "errorMsg")):
                    return [{"id": None, "message": str(row), "row": row} for row in v if _row_failed(row)]
    return []


def format_summary(failures: list[dict]) -> str:
    if not failures:
        return ""
    lines = []
    for f in failures[:5]:
        ident = f.get("id") or "?"
        msg = f.get("message") or "(no message)"
        lines.append(f"  - {ident}: {msg}")
    suffix = f"\n  ... and {len(failures) - 5} more" if len(failures) > 5 else ""
    return "Partial failure details:\n" + "\n".join(lines) + suffix
