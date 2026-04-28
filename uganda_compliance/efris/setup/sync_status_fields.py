"""Custom-field installer for EFRIS sync-status stamps.

Adds `efris_sync_status`, `efris_sync_error`, `efris_sync_job` to the source
doctypes whose flows can run via the EFRIS Sync Job queue. Idempotent — safe
to run on every `after_migrate`.

These fields are intentionally Read-Only on the form; they're populated by
`dispatch.run_job` when a queued URA call completes, so users see the current
sync state directly on the source doc (Item, Sales Invoice, etc.) without
having to open the EFRIS Sync Job list.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Doctypes that can be the `reference_doctype` of an EFRIS Sync Job. Add to
# this list as more flows are migrated to the dispatcher.
TARGET_DOCTYPES = (
    "Item",
    "Sales Invoice",
    "Stock Entry",
    "Stock Reconciliation",
    "Customer",
    "Company",
    "Purchase Receipt",
)


def _field_defs(insert_after: str | None) -> list[dict]:
    return [
        {
            "fieldname": "efris_sync_section",
            "label": "EFRIS Sync",
            "fieldtype": "Section Break",
            "insert_after": insert_after,
            "collapsible": 1,
            "depends_on": "eval:doc.efris_sync_status",
        },
        {
            "fieldname": "efris_sync_status",
            "label": "EFRIS Sync Status",
            "fieldtype": "Select",
            "options": "\nPending\nIn Progress\nSynced\nFailed\nCancelled",
            "read_only": 1,
            "in_standard_filter": 1,
            "insert_after": "efris_sync_section",
        },
        {
            "fieldname": "efris_sync_job",
            "label": "EFRIS Sync Job",
            "fieldtype": "Link",
            "options": "EFRIS Sync Job",
            "read_only": 1,
            "insert_after": "efris_sync_status",
        },
        {
            "fieldname": "efris_sync_error",
            "label": "EFRIS Sync Error",
            "fieldtype": "Small Text",
            "read_only": 1,
            "insert_after": "efris_sync_job",
        },
    ]


def install() -> None:
    fields_per_doctype = {}
    for dt in TARGET_DOCTYPES:
        # Anchor section at the bottom; pick a stable existing field per doctype.
        anchor = _bottom_anchor(dt)
        if not anchor:
            continue
        fields_per_doctype[dt] = _field_defs(anchor)

    if fields_per_doctype:
        create_custom_fields(fields_per_doctype, ignore_validate=True, update=True)


def _bottom_anchor(doctype: str) -> str | None:
    """Return a stable, late-position field on the doctype to anchor our section."""
    fallbacks = {
        "Item": "description",
        "Sales Invoice": "remarks",
        "Stock Entry": "remarks",
        "Stock Reconciliation": "remarks",
        "Customer": "customer_details",
        "Company": "company_description",
        "Purchase Receipt": "remarks",
    }
    candidate = fallbacks.get(doctype)
    if candidate and frappe.db.exists("DocField", {"parent": doctype, "fieldname": candidate}):
        return candidate
    # Final fallback: any field that exists.
    row = frappe.db.get_value(
        "DocField",
        filters={"parent": doctype},
        fieldname="fieldname",
        order_by="idx desc",
    )
    return row
